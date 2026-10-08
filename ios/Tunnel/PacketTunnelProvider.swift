import Foundation
import NetworkExtension

/// The VPN itself: iOS hands this extension a utun interface, Xray reads and
/// writes its packets directly (tun inbound with the utun fd).
final class PacketTunnelProvider: NEPacketTunnelProvider {
    /// The app writes this placeholder where the utun fd goes in the Xray config.
    static let fdPlaceholder = "__SQUAD_TUN_FD__"

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        guard let proto = protocolConfiguration as? NETunnelProviderProtocol,
              let config = proto.providerConfiguration?["config"] as? String
        else {
            completionHandler(Self.fail("Нет настроек сервера. Открой SQUAD VPN и подключись оттуда."))
            return
        }

        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: "254.1.1.1")
        let ipv4 = NEIPv4Settings(addresses: ["198.18.0.1"], subnetMasks: ["255.255.0.0"])
        ipv4.includedRoutes = [NEIPv4Route.default()]
        settings.ipv4Settings = ipv4
        let ipv6 = NEIPv6Settings(addresses: ["fd6e:a81b:704f:1211::1"], networkPrefixLengths: [64])
        ipv6.includedRoutes = [NEIPv6Route.default()]
        settings.ipv6Settings = ipv6
        // Xray answers DNS itself (port 53 inside the tunnel goes to dns-out).
        let dns = NEDNSSettings(servers: ["1.1.1.1"])
        dns.matchDomains = [""]
        settings.dnsSettings = dns
        settings.mtu = 1500

        setTunnelNetworkSettings(settings) { error in
            if let error {
                completionHandler(error)
                return
            }
            guard let fd = self.tunnelFd else {
                completionHandler(Self.fail("iOS не отдала VPN-интерфейс"))
                return
            }
            let json = config.replacingOccurrences(of: Self.fdPlaceholder, with: String(fd))
            let result = Xray.run(json)
            completionHandler(result.success ? nil : Self.fail("Ядро Xray не запустилось: \(result.error)"))
        }
    }

    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        Xray.stop()
        completionHandler()
    }

    /// The app asks "state" to show the core version and whether it runs.
    override func handleAppMessage(_ messageData: Data, completionHandler: ((Data?) -> Void)?) {
        let state = Xray.invoke("getXrayState").data as? [String: Any]
        let reply: [String: Any] = ["running": state?["running"] as? Bool ?? false, "core": Xray.version]
        completionHandler?(try? JSONSerialization.data(withJSONObject: reply))
    }

    /// The utun file descriptor: NEPacketTunnelFlow keeps it private, so look
    /// for the open socket whose interface name starts with "utun".
    private var tunnelFd: Int32? {
        if let fd = packetFlow.value(forKeyPath: "socket.fileDescriptor") as? Int32 { return fd }
        var name = [CChar](repeating: 0, count: Int(IFNAMSIZ))
        for fd: Int32 in 0...1024 {
            var len = socklen_t(name.count)
            // SYSPROTO_CONTROL = 2, UTUN_OPT_IFNAME = 2
            if getsockopt(fd, 2, 2, &name, &len) == 0, String(cString: name).hasPrefix("utun") {
                return fd
            }
        }
        return nil
    }

    private static func fail(_ message: String) -> NSError {
        NSError(domain: "com.squad.vpn.tunnel", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
