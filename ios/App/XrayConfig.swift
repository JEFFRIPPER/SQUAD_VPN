import Foundation

/// Xray configs: the running VPN and one-server configs for ping tests.
/// Same routing as android/…/core/XrayConfig.kt, minus the local SOCKS port
/// (on iPhone the app itself goes through the VPN).
enum XrayConfig {
    static let tagProxy = "proxy"
    static let testURL = "https://www.gstatic.com/generate_204"
    /// The tunnel extension puts the utun fd here.
    static let fdPlaceholder = "__SQUAD_TUN_FD__" // same string in PacketTunnelProvider
    private static let tagFragment = "fragment"
    private static let ruDNS = "77.88.8.8"
    private static let ruDomains = ["domain:ru", "domain:su", "domain:xn--p1ai", "domain:xn--p1acf", "domain:xn--d1acj3b"]
    private static let privateCIDRs = [
        "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.168.0.0/16", "224.0.0.0/4", "fc00::/7", "fe80::/10",
    ]

    /// Carried over TCP: a plain connect already shows whether the server is there.
    static func overTCP(_ node: Node) -> Bool {
        guard let stream = node.outbound["streamSettings"] as? [String: Any] else { return true }
        if ["hysteria", "kcp", "quic"].contains(stream["network"] as? String ?? "") { return false }
        let alpn = ((stream["tlsSettings"] as? [String: Any])?["alpn"] as? [String]) ?? []
        return !alpn.contains("h3")
    }

    private static func fragmentable(_ node: Node) -> Bool {
        let network = (node.outbound["streamSettings"] as? [String: Any])?["network"] as? String ?? ""
        return !["hysteria", "kcp", "quic"].contains(network)
    }

    /// Anti-DPI: the TLS ClientHello to the server leaves in small pieces.
    private static var fragmentOutbound: [String: Any] {
        [
            "tag": tagFragment,
            "protocol": "freedom",
            "settings": [
                "domainStrategy": "AsIs",
                "fragment": ["packets": "tlshello", "length": "100-200", "interval": "10-20"],
            ] as [String: Any],
            "streamSettings": ["sockopt": ["tcpNoDelay": true]],
        ]
    }

    private static func proxyOutbound(_ node: Node, fragment: Bool) -> [String: Any] {
        var outbound = node.outbound
        outbound["tag"] = tagProxy
        if fragment {
            var stream = outbound["streamSettings"] as? [String: Any] ?? [:]
            var sockopt = stream["sockopt"] as? [String: Any] ?? [:]
            sockopt["dialerProxy"] = tagFragment
            stream["sockopt"] = sockopt
            outbound["streamSettings"] = stream
        }
        return outbound
    }

    static func vpn(_ node: Node, ruDirect: Bool, fragment: Bool) -> String {
        let useFragment = fragment && fragmentable(node)
        let sniffing: [String: Any] = ["enabled": true, "destOverride": ["http", "tls", "quic"], "routeOnly": true]
        let inbounds: [[String: Any]] = [[
            "tag": "tun",
            "protocol": "tun",
            "settings": ["name": "utun", "mtu": 1500, "userLevel": 8] as [String: Any],
            "sniffing": sniffing,
        ]]
        var outbounds: [[String: Any]] = [
            proxyOutbound(node, fragment: useFragment),
            ["tag": "direct", "protocol": "freedom", "settings": ["domainStrategy": "UseIPv4"]],
            ["tag": "block", "protocol": "blackhole"],
            ["tag": "dns-out", "protocol": "dns"],
        ]
        if useFragment { outbounds.append(fragmentOutbound) }

        var rules: [[String: Any]] = [
            ["inboundTag": ["tun"], "port": "53", "outboundTag": "dns-out"],
            ["ip": privateCIDRs, "outboundTag": "direct"],
        ]
        var servers: [Any] = []
        if ruDirect {
            rules.append(["ip": [ruDNS], "port": "53", "outboundTag": "direct"])
            rules.append(["domain": ruDomains, "outboundTag": "direct"])
            servers.append(["address": ruDNS, "domains": ruDomains, "skipFallback": true] as [String: Any])
        }
        servers += ["1.1.1.1", "8.8.8.8"]
        // QUIC through most free servers is slow or dropped; browsers fall back to TCP.
        rules.append(["network": "udp", "port": "443", "outboundTag": "block"])

        let config: [String: Any] = [
            "env": ["xray.tun.fd": fdPlaceholder],
            "log": ["loglevel": "warning"],
            "policy": ["levels": ["8": ["handshake": 4, "connIdle": 300, "uplinkOnly": 1, "downlinkOnly": 1]]],
            "dns": ["servers": servers, "queryStrategy": "UseIPv4"] as [String: Any],
            "inbounds": inbounds,
            "outbounds": outbounds,
            "routing": ["domainStrategy": "AsIs", "rules": rules] as [String: Any],
        ]
        return json(config)
    }

    /// One-server config for libXray's pingBatch: the server is the "proxy" outbound.
    static func probe(_ node: Node, fragment: Bool) -> String {
        var outbounds = [proxyOutbound(node, fragment: fragment && fragmentable(node))]
        if fragment && fragmentable(node) { outbounds.append(fragmentOutbound) }
        return json(["log": ["loglevel": "none"], "outbounds": outbounds] as [String: Any])
    }

    static func json(_ object: Any) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return "{}" }
        return String(data: data, encoding: .utf8) ?? "{}"
    }
}
