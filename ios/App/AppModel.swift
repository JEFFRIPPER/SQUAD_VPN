import Foundation
import NetworkExtension
import SwiftUI

enum VpnState: Equatable {
    case off, connecting, on, stopping
}

/// Everything the screens show: servers, pings, the VPN state.
@MainActor
final class AppModel: ObservableObject {
    @Published var profile: Profile = Prefs.profile
    @Published var nodes: [Node] = []
    @Published var pings: [String: Int] = Prefs.pings
    @Published var selected: String? = Prefs.selected
    @Published var state: VpnState = .off
    @Published var connectedNode: String?
    @Published var connectedSince: Date?
    @Published var stage = ""
    @Published var message: String?
    @Published var progress: (done: Int, total: Int)?
    @Published var loading = false
    @Published var ruDirect = Prefs.ruDirect { didSet { Prefs.ruDirect = ruDirect } }
    @Published var antiDPI = Prefs.antiDPI { didSet { Prefs.antiDPI = antiDPI } }
    @Published var hideDead = Prefs.hideDead { didSet { Prefs.hideDead = hideDead } }

    private var manager: NETunnelProviderManager?
    private var observer: NSObjectProtocol?
    private var check: Task<Void, Never>?
    private var connectTask: Task<Void, Never>?

    static let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"

    /// Servers in list order: by ping, unchecked after checked, dead last.
    var sortedNodes: [Node] {
        let list = hideDead ? nodes.filter { pings[$0.id] != Pinger.dead } : nodes
        return list.sorted { rank($0) < rank($1) }
    }

    private func rank(_ node: Node) -> Int {
        guard let ms = pings[node.id] else { return 1_000_000 }
        return ms == Pinger.dead ? 2_000_000 : ms
    }

    var currentNode: Node? {
        let id = connectedNode ?? selected
        return nodes.first { $0.id == id } ?? (selected == nil ? sortedNodes.first { (pings[$0.id] ?? -1) > 0 } : nil)
    }

    var aliveCount: Int { nodes.filter { (pings[$0.id] ?? -1) > 0 }.count }

    // MARK: - Start

    func start() async {
        nodes = Subscriptions.cached(profile)
        await loadManager()
        await reload(force: false)
        if pingsStale { startCheck() }
    }

    private var pingsStale: Bool {
        Date().timeIntervalSince(Prefs.pingedAt ?? .distantPast) > 30 * 60 || aliveCount == 0
    }

    func setProfile(_ value: Profile) {
        guard value != profile else { return }
        profile = value
        Prefs.profile = value
        select(nil)
        nodes = Subscriptions.cached(value)
        Task {
            await reload(force: false)
            startCheck()
        }
    }

    func reload(force: Bool) async {
        loading = true
        defer { loading = false }
        do {
            nodes = try await Subscriptions.load(profile, force: force)
            if force { message = "Подписка обновлена: \(nodes.count) серверов" }
        } catch {
            if nodes.isEmpty || force { message = error.localizedDescription }
        }
    }

    func select(_ id: String?) {
        selected = id
        Prefs.selected = id
    }

    // MARK: - Ping

    var checking: Bool { check != nil }

    func startCheck() {
        check?.cancel()
        let list = nodes
        guard !list.isEmpty else { return }
        progress = (0, list.count)
        let fragment = antiDPI
        check = Task {
            await Pinger.check(list, fragment: fragment) { [weak self] id, ms in
                self?.pings[id] = ms
            } onProgress: { [weak self] done, total in
                self?.progress = (done, total)
            }
            if !Task.isCancelled {
                Prefs.pings = pings
                Prefs.pingedAt = Date()
            }
            progress = nil
            check = nil
        }
    }

    func stopCheck() {
        check?.cancel()
        check = nil
        progress = nil
        Prefs.pings = pings
    }

    // MARK: - VPN

    func toggle() {
        switch state {
        case .off: connect()
        case .connecting:
            connectTask?.cancel()
            manager?.connection.stopVPNTunnel()
        case .on: manager?.connection.stopVPNTunnel()
        case .stopping: break
        }
    }

    private func loadManager() async {
        let managers = (try? await NETunnelProviderManager.loadAllFromPreferences()) ?? []
        manager = managers.first
        if let manager { watch(manager) }
        updateState()
        if state == .on {
            connectedNode = (manager?.protocolConfiguration as? NETunnelProviderProtocol)?.providerConfiguration?["node"] as? String
        }
    }

    private func watch(_ manager: NETunnelProviderManager) {
        if let observer { NotificationCenter.default.removeObserver(observer) }
        observer = NotificationCenter.default.addObserver(
            forName: .NEVPNStatusDidChange, object: manager.connection, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.updateState() }
        }
    }

    private func updateState() {
        let status = manager?.connection.status ?? .invalid
        let busy = connectTask != nil
        switch status {
        case .connected:
            state = busy ? .connecting : .on
            connectedSince = manager?.connection.connectedDate
        case .connecting, .reasserting: state = .connecting
        case .disconnecting: state = busy ? .connecting : .stopping
        default:
            state = busy ? .connecting : .off
            if !busy { connectedNode = nil; connectedSince = nil }
        }
    }

    /// Candidates in order: the chosen server; or recent good ones (white
    /// lists), then the fastest living. Each gets one try.
    private func candidates() -> [Node] {
        if let id = selected, let node = nodes.first(where: { $0.id == id }) { return [node] }
        let alive = sortedNodes.filter { (pings[$0.id] ?? -1) > 0 }
        let good = Prefs.good.compactMap { id in nodes.first { $0.id == id } }
        var seen = Set<String>()
        return (good + alive).filter { seen.insert($0.id).inserted }
    }

    func connect() {
        message = nil
        connectTask = Task {
            state = .connecting
            defer {
                connectTask = nil
                stage = ""
                updateState()
            }
            if nodes.isEmpty { await reload(force: false) }
            if selected == nil && (pingsStale || checking) {
                stage = "Проверяю серверы…"
                startCheck()
                while checking, !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 300_000_000)
                    // TCP answers are enough to start: each try below checks the internet for real.
                    if aliveCount >= 5, (progress?.done ?? 0) >= (progress?.total ?? 0) {
                        stopCheck()
                        break
                    }
                }
            }
            let list = Array(candidates().prefix(profile == .whitelist ? 5 : 3))
            guard !list.isEmpty else {
                message = nodes.isEmpty ? "Нет серверов: обнови подписку" : "Ни один сервер не ответил. Попробуй другую подписку или «Обход DPI»"
                return
            }
            for (i, node) in list.enumerated() where !Task.isCancelled {
                stage = list.count > 1 ? "Подключаюсь (\(i + 1) из \(list.count)): \(node.name)" : "Подключаюсь: \(node.name)"
                if await tryConnect(node) {
                    connectedNode = node.id
                    Prefs.good = [node.id] + Prefs.good.filter { $0 != node.id }
                    return
                }
            }
            if !Task.isCancelled && message == nil { message = "Не удалось подключиться. Попробуй другой сервер" }
        }
    }

    /// Starts the tunnel with [node] and checks that the internet opens through it.
    private func tryConnect(_ node: Node) async -> Bool {
        let manager = manager ?? NETunnelProviderManager()
        let proto = NETunnelProviderProtocol()
        proto.providerBundleIdentifier = (Bundle.main.bundleIdentifier ?? "com.squad.vpn") + ".tunnel"
        proto.serverAddress = node.name
        proto.providerConfiguration = [
            "config": XrayConfig.vpn(node, ruDirect: ruDirect && profile != .whitelist, fragment: antiDPI),
            "node": node.id,
        ]
        manager.protocolConfiguration = proto
        manager.localizedDescription = "SQUAD VPN"
        manager.isEnabled = true
        do {
            if manager.connection.status != .disconnected && manager.connection.status != .invalid {
                manager.connection.stopVPNTunnel()
                try? await Task.sleep(nanoseconds: 800_000_000)
            }
            try await manager.saveToPreferences()
            try await manager.loadFromPreferences()
            self.manager = manager
            watch(manager)
            try manager.connection.startVPNTunnel()
        } catch {
            message = "VPN не запустился: \(error.localizedDescription)"
            return false
        }
        // Up to 12 s for the tunnel to come up.
        for _ in 0..<40 {
            if Task.isCancelled { return false }
            let status = manager.connection.status
            if status == .connected { break }
            if status == .disconnected || status == .invalid {
                let error: Error? = await withCheckedContinuation { done in
                    manager.connection.fetchLastDisconnectError { done.resume(returning: $0) }
                }
                if let error { message = error.localizedDescription }
                return false
            }
            try? await Task.sleep(nanoseconds: 300_000_000)
        }
        guard manager.connection.status == .connected else {
            manager.connection.stopVPNTunnel()
            return false
        }
        stage = "Проверяю интернет…"
        if await internetWorks() { return true }
        manager.connection.stopVPNTunnel()
        try? await Task.sleep(nanoseconds: 700_000_000)
        return false
    }

    private func internetWorks() async -> Bool {
        guard let url = URL(string: XrayConfig.testURL) else { return false }
        for _ in 0..<2 {
            var request = URLRequest(url: url, timeoutInterval: 6)
            request.cachePolicy = .reloadIgnoringLocalCacheData
            if let (_, response) = try? await URLSession.shared.data(for: request),
               let code = (response as? HTTPURLResponse)?.statusCode, code == 204 || code == 200 {
                return true
            }
        }
        return false
    }

    // MARK: - Custom keys

    /// "Своя ссылка": a subscription URL or the keys themselves.
    func setCustom(_ text: String) {
        Prefs.customURL = text.trimmingCharacters(in: .whitespacesAndNewlines)
        Subscriptions.forget(.custom)
        if profile != .custom { setProfile(.custom) } else {
            Task {
                await reload(force: true)
                startCheck()
            }
        }
    }
}
