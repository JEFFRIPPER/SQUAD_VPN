import Foundation

/// Subscriptions published by SQUAD VPN (branch subs), plus the user's own link.
enum Profile: String, CaseIterable, Identifiable {
    case top, best, whitelist, custom

    var id: String { rawValue }

    var title: String {
        switch self {
        case .top: return "Топ-10"
        case .best: return "Лучшие 300"
        case .whitelist: return "Белые списки"
        case .custom: return "Своя ссылка"
        }
    }

    var hint: String {
        switch self {
        case .top: return "Самые надёжные серверы. Начни с неё"
        case .best: return "300 лучших серверов, больше выбор"
        case .whitelist: return "До 100 серверов на случай, когда глушат мобильный интернет. Обнови заранее"
        case .custom: return "Подписка v2ray / base64 или ключи vless://, vmess://, trojan://, ss://"
        }
    }

    var urls: [URL] {
        if self == .custom {
            return [Prefs.customURL].filter { $0.hasPrefix("http") }.compactMap(URL.init(string:))
        }
        return [
            "https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/\(rawValue).b64",
            "https://cdn.jsdelivr.net/gh/JEFFRIPPER/SQUAD_VPN@subs/\(rawValue).b64",
        ].compactMap(URL.init(string:))
    }
}

/// Settings, kept in UserDefaults.
enum Prefs {
    private static let d = UserDefaults.standard

    static var profile: Profile {
        get { Profile(rawValue: d.string(forKey: "profile") ?? "") ?? .top }
        set { d.set(newValue.rawValue, forKey: "profile") }
    }
    static var customURL: String {
        get { d.string(forKey: "custom_url") ?? "" }
        set { d.set(newValue, forKey: "custom_url") }
    }
    /// Server picked by hand; nil = the fastest one.
    static var selected: String? {
        get { d.string(forKey: "selected") }
        set { d.set(newValue, forKey: "selected") }
    }
    static var ruDirect: Bool {
        get { d.object(forKey: "ru_direct") as? Bool ?? true }
        set { d.set(newValue, forKey: "ru_direct") }
    }
    static var antiDPI: Bool {
        get { d.bool(forKey: "anti_dpi") }
        set { d.set(newValue, forKey: "anti_dpi") }
    }
    static var hideDead: Bool {
        get { d.bool(forKey: "hide_dead") }
        set { d.set(newValue, forKey: "hide_dead") }
    }
    /// Servers that connected recently, newest first (the white-list profile tries them first).
    static var good: [String] {
        get { d.stringArray(forKey: "good") ?? [] }
        set { d.set(Array(newValue.prefix(5)), forKey: "good") }
    }
    static var pings: [String: Int] {
        get { d.dictionary(forKey: "pings") as? [String: Int] ?? [:] }
        set { d.set(newValue, forKey: "pings") }
    }
    static var pingedAt: Date? {
        get { d.object(forKey: "pinged_at") as? Date }
        set { d.set(newValue, forKey: "pinged_at") }
    }
}

/// Downloads a profile's subscription and keeps the last good copy on disk.
enum Subscriptions {
    private static let staleAfter: TimeInterval = 60 * 60

    private static func file(_ profile: Profile) -> URL {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("subs", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("\(profile.rawValue).txt")
    }

    static func forget(_ profile: Profile) { try? FileManager.default.removeItem(at: file(profile)) }

    static func updatedAt(_ profile: Profile) -> Date? {
        (try? FileManager.default.attributesOfItem(atPath: file(profile).path))?[.modificationDate] as? Date
    }

    /// The last downloaded copy, or the one built into the app: on white lists
    /// GitHub may never open, and the app must still have servers to start from.
    static func cached(_ profile: Profile) -> [Node] {
        if let text = try? String(contentsOf: file(profile), encoding: .utf8) {
            return Links.parseSubscription(text)
        }
        guard let url = Bundle.main.url(forResource: profile.rawValue, withExtension: "b64", subdirectory: "subs"),
              let text = try? String(contentsOf: url, encoding: .utf8)
        else { return [] }
        return Links.parseSubscription(text)
    }

    /// Fresh copy from the network; throws when nothing usable came back.
    static func refresh(_ profile: Profile) async throws -> [Node] {
        let inline = profile == .custom && profile.urls.isEmpty && Prefs.customURL.contains("://")
        var text: String?
        if inline {
            text = Prefs.customURL
        } else {
            if profile.urls.isEmpty { throw AppError("Укажи ссылку на подписку в настройках") }
            var lastError: Error = AppError("Подписка не скачалась")
            for url in profile.urls {
                do {
                    var request = URLRequest(url: url, timeoutInterval: 15)
                    request.setValue("SQUAD-VPN-iOS", forHTTPHeaderField: "User-Agent")
                    let (data, response) = try await URLSession.shared.data(for: request)
                    if (response as? HTTPURLResponse)?.statusCode == 200, let body = String(data: data, encoding: .utf8) {
                        text = body
                        break
                    }
                } catch {
                    lastError = error
                }
            }
            if text == nil { throw lastError }
        }
        let nodes = Links.parseSubscription(text ?? "")
        if nodes.isEmpty { throw AppError("В подписке нет подходящих серверов") }
        try? text?.write(to: file(profile), atomically: true, encoding: .utf8)
        return nodes
    }

    /// Cached servers, refreshed first when the copy is old; the cache wins if the network fails.
    static func load(_ profile: Profile, force: Bool = false) async throws -> [Node] {
        let cached = cached(profile)
        let stale = Date().timeIntervalSince(updatedAt(profile) ?? .distantPast) > staleAfter
        if cached.isEmpty || stale || force {
            do {
                return try await refresh(profile)
            } catch {
                if cached.isEmpty { throw error }
            }
        }
        return cached
    }
}

struct AppError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
