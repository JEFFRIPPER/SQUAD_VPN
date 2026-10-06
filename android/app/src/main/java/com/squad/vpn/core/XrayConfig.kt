package com.squad.vpn.core

import org.json.JSONArray
import org.json.JSONObject

/** Builds Xray configs: the running VPN and a one-node config for ping tests. */
object XrayConfig {
    const val TAG_PROXY = "proxy"
    const val SOCKS_PORT = 10808
    const val TEST_URL = "https://www.gstatic.com/generate_204"
    const val MTU = 1500

    /** DNS the VPN interface hands to apps; Xray answers it itself (dns-out). */
    const val TUN_DNS = "1.1.1.1"
    private const val RU_DNS = "77.88.8.8"

    /**
     * Every app on the phone can reach 127.0.0.1, and an open SOCKS port
     * gives away the VPN and the server's address. The port asks for a
     * password made anew on every app start; only this app knows it ([Http]).
     */
    val socksUser: String = randomHex(8)
    val socksPass: String = randomHex(16)

    private fun randomHex(bytes: Int): String =
        ByteArray(bytes).also { java.security.SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }

    // Russian sites go around the VPN when asked: banks and state services
    // often refuse foreign addresses. Never in the white-list profile, where
    // only the white-listed server reaches the internet.
    private val ruDomains = listOf("domain:ru", "domain:su", "domain:xn--p1ai", "domain:xn--p1acf", "domain:xn--d1acj3b")

    private val privateCidrs = listOf(
        "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.168.0.0/16", "224.0.0.0/4", "fc00::/7", "fe80::/10",
    )

    fun vpn(node: Node, ruDirect: Boolean, logLevel: String = "warning"): String {
        val sniffing = JSONObject()
            .put("enabled", true)
            .put("destOverride", JSONArray(listOf("http", "tls", "quic")))
            .put("routeOnly", true)

        val inbounds = JSONArray()
            .put(
                JSONObject()
                    .put("tag", "tun")
                    .put("protocol", "tun")
                    .put("settings", JSONObject().put("name", "xray0").put("MTU", MTU).put("userLevel", 8))
                    .put("sniffing", sniffing),
            )
            // The app itself is outside the VPN; it reaches the internet through
            // this port when it has to (subscription refresh in white-list mode).
            .put(
                JSONObject()
                    .put("tag", "socks")
                    .put("listen", "127.0.0.1")
                    .put("port", SOCKS_PORT)
                    .put("protocol", "socks")
                    .put(
                        "settings",
                        JSONObject()
                            .put("auth", "password")
                            .put("accounts", JSONArray().put(JSONObject().put("user", socksUser).put("pass", socksPass)))
                            .put("udp", true)
                            .put("userLevel", 8),
                    )
                    .put("sniffing", sniffing),
            )

        val outbounds = JSONArray()
            .put(proxyOutbound(node))
            .put(
                JSONObject()
                    .put("tag", "direct")
                    .put("protocol", "freedom")
                    .put("settings", JSONObject().put("domainStrategy", "UseIPv4")),
            )
            .put(JSONObject().put("tag", "block").put("protocol", "blackhole"))
            .put(JSONObject().put("tag", "dns-out").put("protocol", "dns"))

        val rules = JSONArray()
            .put(JSONObject().put("inboundTag", JSONArray().put("tun")).put("port", "53").put("outboundTag", "dns-out"))
            .put(JSONObject().put("ip", JSONArray(privateCidrs)).put("outboundTag", "direct"))
        val servers = JSONArray()
        if (ruDirect) {
            rules.put(JSONObject().put("ip", JSONArray().put(RU_DNS)).put("port", "53").put("outboundTag", "direct"))
            rules.put(JSONObject().put("domain", JSONArray(ruDomains)).put("outboundTag", "direct"))
            servers.put(
                JSONObject()
                    .put("address", RU_DNS)
                    .put("domains", JSONArray(ruDomains))
                    .put("skipFallback", true),
            )
        }
        servers.put("1.1.1.1").put("8.8.8.8")
        // QUIC through most free servers is slow or dropped; browsers fall back to TCP.
        rules.put(
            JSONObject().put("network", "udp").put("port", "443").put("outboundTag", "block"),
        )

        return JSONObject()
            .put("log", JSONObject().put("loglevel", logLevel))
            .put("stats", JSONObject())
            .put(
                "policy",
                JSONObject()
                    .put(
                        "levels",
                        JSONObject().put(
                            "8",
                            JSONObject()
                                .put("handshake", 4)
                                .put("connIdle", 300)
                                .put("uplinkOnly", 1)
                                .put("downlinkOnly", 1),
                        ),
                    )
                    .put(
                        "system",
                        JSONObject().put("statsOutboundUplink", true).put("statsOutboundDownlink", true),
                    ),
            )
            .put("dns", JSONObject().put("servers", servers).put("queryStrategy", "UseIPv4"))
            .put("inbounds", inbounds)
            .put("outbounds", outbounds)
            .put("routing", JSONObject().put("domainStrategy", "AsIs").put("rules", rules))
            .toString()
    }

    /** Minimal config for Libv2ray.measureOutboundDelay: the node is the first outbound. */
    fun probe(node: Node): String =
        JSONObject()
            .put("log", JSONObject().put("loglevel", "none"))
            .put("outbounds", JSONArray().put(proxyOutbound(node)))
            .toString()

    private fun proxyOutbound(node: Node): JSONObject =
        JSONObject(node.outbound.toString()).put("tag", TAG_PROXY)
}
