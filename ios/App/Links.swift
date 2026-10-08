import CryptoKit
import Foundation

/// One server from a subscription, already turned into an Xray outbound (without a tag).
struct Node: Identifiable, Hashable {
    let name: String
    let proto: String
    let server: String
    let port: Int
    let outbound: [String: Any]
    /// The subscription line this server came from.
    let link: String

    /// Same link (without its display name) => same key, so pings survive a refresh.
    let id: String

    init(name: String, proto: String, server: String, port: Int, outbound: [String: Any], link: String) {
        self.name = name
        self.proto = proto
        self.server = server
        self.port = port
        self.outbound = outbound
        self.link = link
        id = Links.linkKey(link)
    }

    static func == (a: Node, b: Node) -> Bool { a.id == b.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }

    func renamed(_ newName: String) -> Node {
        Node(name: newName, proto: proto, server: server, port: port, outbound: outbound, link: link)
    }
}

/// Share links (vless/vmess/trojan/ss/hysteria2) -> Xray outbounds: the same
/// rules as android/…/core/Links.kt. Links Xray cannot serve are skipped.
enum Links {
    static func parseSubscription(_ text: String) -> [Node] {
        var nodes: [Node] = []
        var used: [String: Int] = [:]
        var keys = Set<String>()
        for raw in decodeBody(text).components(separatedBy: .newlines) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty || line.hasPrefix("#") { continue }
            guard let node = parse(line), keys.insert(node.id).inserted else { continue }
            let count = (used[node.name] ?? 0) + 1
            used[node.name] = count
            nodes.append(count == 1 ? node : node.renamed("\(node.name) · \(count)"))
        }
        return nodes
    }

    /// Subscriptions come either as plain lines or as one base64 blob.
    static func decodeBody(_ text: String) -> String {
        var trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.hasPrefix("\u{FEFF}") { trimmed.removeFirst() }
        if trimmed.contains("://") { return trimmed }
        let compact = trimmed.components(separatedBy: .whitespacesAndNewlines).joined()
        if let data = decodeBase64(compact), let decoded = String(data: data, encoding: .utf8) { return decoded }
        return trimmed
    }

    static func parse(_ link: String) -> Node? {
        guard let range = link.range(of: "://") else { return nil }
        switch link[..<range.lowerBound].lowercased() {
        case "vless": return vless(Parts(link))
        case "vmess": return vmess(link)
        case "trojan": return trojan(Parts(link))
        case "ss": return shadowsocks(link)
        case "hysteria2", "hy2": return hysteria2(Parts(link))
        default: return nil
        }
    }

    // MARK: - Pieces of a link

    private struct Parts {
        var user = ""
        var host = ""
        var port = 443
        var query: [String: String] = [:]
        var name = ""
        var link = ""

        func q(_ key: String) -> String { query[key] ?? "" }

        init(user: String, host: String, port: Int, query: [String: String], name: String, link: String) {
            self.user = user; self.host = host; self.port = port; self.query = query; self.name = name; self.link = link
        }

        init(_ link: String) {
            self.link = link
            let rest = link.before("#").after("://")
            let authority = rest.before("?").before("/")
            let hostPort = authority.afterLast("@")
            if hostPort.hasPrefix("[") {
                host = hostPort.after("[").before("]")
                port = Int(hostPort.after("]:", missing: "")) ?? 443
            } else {
                host = hostPort.beforeLast(":")
                port = Int(hostPort.afterLast(":", missing: "")) ?? 443
            }
            user = Links.decode(authority.beforeLast("@", missing: ""))
            query = Links.parseQuery(rest.after("?", missing: ""))
            name = Links.decode(link.after("#", missing: "")).trimmingCharacters(in: .whitespaces)
        }
    }

    private static func vless(_ p: Parts) -> Node? {
        if p.user.isEmpty || p.host.isEmpty { return nil }
        var settings = server(p)
        settings["id"] = p.user
        settings["encryption"] = p.q("encryption").or("none")
        if !p.q("flow").isEmpty { settings["flow"] = p.q("flow") }
        guard let stream = stream(p, security: p.q("security")) else { return nil }
        return node("vless", p, settings, stream)
    }

    private static func trojan(_ p: Parts) -> Node? {
        if p.user.isEmpty || p.host.isEmpty { return nil }
        var settings = server(p)
        settings["password"] = p.user
        guard let stream = stream(p, security: p.q("security").or("tls")) else { return nil }
        return node("trojan", p, settings, stream)
    }

    private static func vmess(_ link: String) -> Node? {
        guard let data = decodeBase64(link.after("://").before("#")),
              let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        else { return nil }
        func s(_ key: String) -> String {
            if let v = json[key] as? String { return v.trimmingCharacters(in: .whitespaces) }
            if let v = json[key] as? NSNumber { return v.stringValue }
            return ""
        }
        let host = s("add"), id = s("id")
        if host.isEmpty || id.isEmpty { return nil }
        let net = s("net").or("tcp")
        var query = [
            "type": net, "headerType": s("type"), "host": s("host"), "path": s("path"),
            "serviceName": s("path"), "sni": s("sni"), "alpn": s("alpn"), "fp": s("fp"),
        ]
        if net == "grpc" && s("type") == "multi" { query["mode"] = "multi" }
        let p = Parts(user: id, host: host, port: Int(s("port")) ?? 443, query: query, name: s("ps"), link: link)
        var settings = server(p)
        settings["id"] = id
        settings["security"] = s("scy").or("auto")
        let tls = s("tls")
        guard let stream = stream(p, security: tls == "tls" || tls == "reality" ? tls : "") else { return nil }
        return node("vmess", p, settings, stream)
    }

    private static func shadowsocks(_ link: String) -> Node? {
        let name = decode(link.after("#", missing: "")).trimmingCharacters(in: .whitespaces)
        var rest = link.before("#").after("://")
        let query = parseQuery(rest.after("?", missing: ""))
        rest = rest.before("?")
        while rest.hasSuffix("/") { rest.removeLast() }
        let plugin = query["plugin"] ?? ""
        if !plugin.isEmpty && plugin != "none" { return nil }
        let userInfo: String
        let hostPort: String
        if rest.contains("@") {
            let encoded = decode(rest.beforeLast("@"))
            if encoded.contains(":") {
                userInfo = encoded
            } else {
                guard let d = decodeBase64(encoded), let s = String(data: d, encoding: .utf8) else { return nil }
                userInfo = s
            }
            hostPort = rest.afterLast("@")
        } else {
            guard let d = decodeBase64(rest), let decoded = String(data: d, encoding: .utf8) else { return nil }
            userInfo = decoded.beforeLast("@")
            hostPort = decoded.afterLast("@")
        }
        let method = userInfo.before(":")
        let password = userInfo.after(":", missing: "")
        let host = hostPort.beforeLast(":").trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        guard let port = Int(hostPort.afterLast(":")), !method.isEmpty, !host.isEmpty else { return nil }
        let p = Parts(user: "", host: host, port: port, query: [:], name: name, link: link)
        var settings = server(p)
        settings["method"] = method
        settings["password"] = password
        return node("shadowsocks", p, settings, ["network": "raw"])
    }

    private static func hysteria2(_ p: Parts) -> Node? {
        if p.host.isEmpty { return nil }
        var settings = server(p)
        settings["version"] = 2
        var stream: [String: Any] = [
            "network": "hysteria",
            "hysteriaSettings": ["version": 2, "auth": p.user] as [String: Any],
        ]
        if p.q("obfs") == "salamander" && !p.q("obfs-password").isEmpty {
            let mask: [String: Any] = ["type": "salamander", "settings": ["password": p.q("obfs-password")]]
            stream["finalmask"] = ["udp": [mask]]
        }
        var tls: [String: Any] = ["serverName": p.q("sni").or(p.host), "alpn": ["h3"]]
        pins(p, &tls)
        stream["security"] = "tls"
        stream["tlsSettings"] = tls
        return node("hysteria", p, settings, stream)
    }

    private static func server(_ p: Parts) -> [String: Any] {
        ["address": p.host, "port": p.port, "level": 8]
    }

    private static func node(_ proto: String, _ p: Parts, _ settings: [String: Any], _ stream: [String: Any]) -> Node {
        let outbound: [String: Any] = ["protocol": proto, "settings": settings, "streamSettings": stream]
        let label = proto == "hysteria" ? "hysteria2" : proto
        let clean = p.name.unicodeScalars.map { CharacterSet.controlCharacters.contains($0) ? " " : String($0) }.joined()
            .trimmingCharacters(in: .whitespaces)
        return Node(name: String(clean.or(p.host).prefix(64)), proto: label, server: p.host, port: p.port,
                    outbound: outbound, link: p.link)
    }

    private static func pins(_ p: Parts, _ tls: inout [String: Any]) {
        let pin = p.q("pcs").or(p.q("pinSHA256")).replacingOccurrences(of: ":", with: "").lowercased()
        if pin.range(of: "^[0-9a-f]{64}(,[0-9a-f]{64})*$", options: .regularExpression) != nil {
            tls["pinnedPeerCertSha256"] = pin
        }
        if !p.q("vcn").isEmpty { tls["verifyPeerCertByName"] = p.q("vcn") }
    }

    private static func list(_ value: String) -> [String]? {
        let items = value.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        return items.isEmpty ? nil : items
    }

    /// streamSettings for vless/vmess/trojan; nil when the transport is unknown.
    private static func stream(_ p: Parts, security: String) -> [String: Any]? {
        var stream: [String: Any] = [:]
        let host = p.q("host"), path = p.q("path")
        var sniFromTransport = host
        let network = p.q("type").or("tcp")
        switch network {
        case "tcp", "raw":
            stream["network"] = "raw"
            if p.q("headerType") == "http" {
                var request: [String: Any] = ["path": list(path) ?? ["/"]]
                if let hosts = list(host) { request["headers"] = ["Host": hosts] }
                stream["rawSettings"] = ["header": ["type": "http", "request": request] as [String: Any]]
                sniFromTransport = host.before(",")
            }
        case "ws", "httpupgrade":
            stream["network"] = network
            var settings: [String: Any] = ["path": path.or("/")]
            if !host.isEmpty { settings["host"] = host }
            stream[network == "ws" ? "wsSettings" : "httpupgradeSettings"] = settings
        case "xhttp", "splithttp", "h2", "http":
            stream["network"] = "xhttp"
            var settings: [String: Any] = ["path": path.or("/")]
            if !host.isEmpty { settings["host"] = host.before(",") }
            if !p.q("mode").isEmpty { settings["mode"] = p.q("mode") }
            let extra = p.q("extra")
            if extra.hasPrefix("{"), let obj = try? JSONSerialization.jsonObject(with: Data(extra.utf8)) {
                settings["extra"] = obj
            }
            stream["xhttpSettings"] = settings
            sniFromTransport = host.before(",")
        case "grpc":
            stream["network"] = "grpc"
            var settings: [String: Any] = [
                "serviceName": p.q("serviceName").or(p.q("service_name")),
                "multiMode": p.q("mode") == "multi",
            ]
            if !p.q("authority").isEmpty { settings["authority"] = p.q("authority") }
            stream["grpcSettings"] = settings
            sniFromTransport = p.q("authority")
        default:
            return nil
        }

        switch security {
        case "tls", "xtls":
            var tls: [String: Any] = [:]
            var sni = p.q("sni").or(p.q("peer"))
            if sni.isEmpty { sni = isDomain(sniFromTransport) ? sniFromTransport : (isDomain(p.host) ? p.host : "") }
            if !sni.isEmpty { tls["serverName"] = sni }
            pins(p, &tls)
            if let alpn = list(p.q("alpn")) { tls["alpn"] = alpn }
            if !p.q("fp").isEmpty { tls["fingerprint"] = p.q("fp") }
            if !p.q("ech").isEmpty { tls["echConfigList"] = p.q("ech") }
            stream["security"] = "tls"
            stream["tlsSettings"] = tls
        case "reality":
            let key = p.q("pbk")
            if key.isEmpty { return nil }
            var reality: [String: Any] = [
                "serverName": p.q("sni"), "fingerprint": p.q("fp").or("chrome"),
                "publicKey": key, "shortId": p.q("sid"),
            ]
            if !p.q("spx").isEmpty { reality["spiderX"] = p.q("spx") }
            if !p.q("pqv").isEmpty { reality["mldsa65Verify"] = p.q("pqv") }
            stream["security"] = "reality"
            stream["realitySettings"] = reality
        case "", "none":
            break
        default:
            return nil
        }
        return stream
    }

    private static func isDomain(_ value: String) -> Bool {
        !value.isEmpty && !value.contains(":") && !value.allSatisfy { $0.isNumber || $0 == "." }
    }

    fileprivate static func parseQuery(_ query: String) -> [String: String] {
        var map: [String: String] = [:]
        for pair in query.split(separator: "&") {
            let s = String(pair)
            let key = decode(s.before("="))
            if map[key] == nil { map[key] = decode(s.after("=", missing: "")) }
        }
        return map
    }

    /// Percent-decoding that keeps "+" as is (like the Kotlin version).
    fileprivate static func decode(_ value: String) -> String { value.removingPercentEncoding ?? value }

    /// Key of a subscription line without its display name: link_key() in src/squad_vpn/smart.py.
    static func linkKey(_ link: String) -> String {
        let base = link.trimmingCharacters(in: .whitespaces).before("#")
        let digest = SHA256.hash(data: Data(base.utf8))
        return digest.map { String(format: "%02x", $0) }.joined().prefix(16).description
    }

    static func decodeBase64(_ value: String) -> Data? {
        var clean = value.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while clean.hasSuffix("=") { clean.removeLast() }
        clean += String(repeating: "=", count: (4 - clean.count % 4) % 4)
        return Data(base64Encoded: clean)
    }
}

// Kotlin-style substring helpers: the parsing above reads like Links.kt.
extension String {
    func or(_ fallback: String) -> String { isEmpty ? fallback : self }

    func before(_ sep: String) -> String {
        guard let r = range(of: sep) else { return self }
        return String(self[..<r.lowerBound])
    }

    func after(_ sep: String, missing: String? = nil) -> String {
        guard let r = range(of: sep) else { return missing ?? self }
        return String(self[r.upperBound...])
    }

    func beforeLast(_ sep: String, missing: String? = nil) -> String {
        guard let r = range(of: sep, options: .backwards) else { return missing ?? self }
        return String(self[..<r.lowerBound])
    }

    func afterLast(_ sep: String, missing: String? = nil) -> String {
        guard let r = range(of: sep, options: .backwards) else { return missing ?? self }
        return String(self[r.upperBound...])
    }
}
