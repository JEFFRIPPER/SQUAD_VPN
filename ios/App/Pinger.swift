import Foundation
import Network

/// Server checks in two steps: a plain TCP connect for every server (fast,
/// finds the dead ones), then a real HTTPS request through Xray for the
/// fastest of the living (libXray pingBatch, 5 servers at a time).
enum Pinger {
    static let dead = -1
    private static let connectTimeout: TimeInterval = 3
    private static let coreTimeout = 8
    private static let parallel = 24

    /// TCP connect time in ms, or nil when the server does not answer.
    static func connectTime(_ node: Node) async -> Int? {
        guard let port = NWEndpoint.Port(rawValue: UInt16(clamping: node.port)) else { return nil }
        return await withCheckedContinuation { continuation in
            let connection = NWConnection(host: NWEndpoint.Host(node.server), port: port, using: .tcp)
            let started = Date()
            let once = Once()
            let finish: (Int?) -> Void = { result in
                once.run {
                    connection.cancel()
                    continuation.resume(returning: result)
                }
            }
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready: finish(Int(Date().timeIntervalSince(started) * 1000))
                case .failed, .waiting, .cancelled: finish(nil)
                default: break
                }
            }
            connection.start(queue: .global(qos: .userInitiated))
            DispatchQueue.global().asyncAfter(deadline: .now() + Pinger.connectTimeout) { finish(nil) }
        }
    }

    /// (node, connect ms or nil); 0 = UDP server, TCP cannot tell.
    private static func probeTCP(_ node: Node) async -> (Node, Int?) {
        if !XrayConfig.overTCP(node) { return (node, 0) }
        let ms = await connectTime(node)
        return (node, ms.map { max($0, 1) })
    }

    /// Real delay through each server (up to 5 per call), dead = -1.
    static func coreDelay(_ nodes: [Node], fragment: Bool) async -> [String: Int] {
        await Task.detached(priority: .userInitiated) {
            let configs = nodes.map { ["xrayJson": XrayConfig.probe($0, fragment: fragment), "outboundTag": XrayConfig.tagProxy] }
            let response = Xray.invoke("pingBatch", ["configs": configs, "timeout": Pinger.coreTimeout, "url": XrayConfig.testURL])
            let results = (response.data as? [String: Any])?["results"] as? [[String: Any]] ?? []
            var out: [String: Int] = [:]
            for (i, node) in nodes.enumerated() {
                let item = i < results.count ? results[i] : [:]
                let delay = (item["delay"] as? NSNumber)?.intValue ?? 0
                out[node.id] = (item["success"] as? Bool ?? false) && delay > 0 ? delay : Pinger.dead
            }
            return out
        }.value
    }

    /// Checks [nodes]: every server by TCP, then the [verify] fastest through the core.
    /// [onResult] gets each result as it arrives (on the main actor).
    static func check(
        _ nodes: [Node],
        verify: Int = 25,
        fragment: Bool,
        onResult: @escaping @MainActor (String, Int) -> Void,
        onProgress: @escaping @MainActor (Int, Int) -> Void
    ) async {
        let total = nodes.count
        var done = 0
        var tcp: [(Node, Int)] = []
        var udp: [Node] = []
        await withTaskGroup(of: (Node, Int?).self) { group in
            var next = 0
            while next < min(parallel, nodes.count) {
                let node = nodes[next]
                group.addTask { await Pinger.probeTCP(node) }
                next += 1
            }
            while let (node, ms) = await group.next() {
                if Task.isCancelled { group.cancelAll(); return }
                done += 1
                if ms == 0 {
                    udp.append(node)
                } else if let ms {
                    tcp.append((node, ms))
                    await onResult(node.id, ms)
                } else {
                    await onResult(node.id, dead)
                }
                await onProgress(done, total)
                if next < nodes.count {
                    let node = nodes[next]
                    group.addTask { await Pinger.probeTCP(node) }
                    next += 1
                }
            }
        }
        // The fastest by TCP, plus UDP servers (hysteria2) that TCP cannot see.
        let candidates = tcp.sorted { $0.1 < $1.1 }.prefix(verify).map(\.0) + udp.prefix(10)
        var index = 0
        while index < candidates.count, !Task.isCancelled {
            let chunk = Array(candidates[index..<min(index + 5, candidates.count)])
            for (id, ms) in await coreDelay(chunk, fragment: fragment) {
                await onResult(id, ms)
            }
            index += chunk.count
        }
    }
}

/// Runs a block once, whichever callback comes first.
final class Once: @unchecked Sendable {
    private let lock = NSLock()
    private var done = false

    func run(_ block: () -> Void) {
        lock.lock()
        let first = !done
        done = true
        lock.unlock()
        if first { block() }
    }
}
