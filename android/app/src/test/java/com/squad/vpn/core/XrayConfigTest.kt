package com.squad.vpn.core

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class XrayConfigTest {
    private val node = Links.parse("vless://id@1.2.3.4:443?security=reality&pbk=KEY&sni=a.com#n")!!

    private fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }

    private fun rules(config: JSONObject) = config.getJSONObject("routing").getJSONArray("rules").objects()

    @Test
    fun vpnConfig() {
        val config = JSONObject(XrayConfig.vpn(node, ruDirect = false))
        val outbounds = config.getJSONArray("outbounds").objects()
        assertEquals("proxy", outbounds[0].getString("tag"))
        assertEquals("vless", outbounds[0].getString("protocol"))
        assertEquals(listOf("proxy", "direct", "block", "dns-out"), outbounds.map { it.getString("tag") })

        val inbounds = config.getJSONArray("inbounds").objects()
        assertEquals("tun", inbounds[0].getString("protocol"))
        assertEquals(XrayConfig.MTU, inbounds[0].getJSONObject("settings").getInt("MTU"))
        assertEquals(XrayConfig.SOCKS_PORT, inbounds[1].getInt("port"))
        assertEquals("127.0.0.1", inbounds[1].getString("listen"))

        val rules = rules(config)
        assertEquals("dns-out", rules[0].getString("outboundTag"))
        assertTrue(rules.any { it.optString("network") == "udp" && it.optString("port") == "443" && it.getString("outboundTag") == "block" })
        assertFalse(rules.any { it.has("domain") })
        // Every rule points at an outbound that exists.
        val tags = outbounds.map { it.getString("tag") }.toSet()
        assertTrue(rules.all { it.getString("outboundTag") in tags })
    }

    @Test
    fun russianSitesDirect() {
        val config = JSONObject(XrayConfig.vpn(node, ruDirect = true))
        val domainRule = rules(config).single { it.has("domain") }
        assertEquals("direct", domainRule.getString("outboundTag"))
        assertTrue(domainRule.getJSONArray("domain").toString().contains("domain:ru"))
        val servers = config.getJSONObject("dns").getJSONArray("servers")
        assertTrue(servers.get(0) is JSONObject)
    }

    @Test
    fun probeHasOnlyTheNode() {
        val config = JSONObject(XrayConfig.probe(node))
        val outbounds = config.getJSONArray("outbounds")
        assertEquals(1, outbounds.length())
        assertEquals("proxy", outbounds.getJSONObject(0).getString("tag"))
    }

    @Test
    fun configsDoNotChangeTheNode() {
        val before = node.key
        XrayConfig.vpn(node, ruDirect = true)
        XrayConfig.probe(node)
        assertFalse(node.outbound.has("tag"))
        assertEquals(before, node.key)
    }

    @Test
    fun antiDpiFragment() {
        val config = JSONObject(XrayConfig.vpn(node, ruDirect = false, fragment = true))
        val outbounds = config.getJSONArray("outbounds").objects()
        val fragment = outbounds.single { it.getString("tag") == "fragment" }
        assertEquals("freedom", fragment.getString("protocol"))
        assertEquals("tlshello", fragment.getJSONObject("settings").getJSONObject("fragment").getString("packets"))
        val sockopt = outbounds[0].getJSONObject("streamSettings").getJSONObject("sockopt")
        assertEquals("fragment", sockopt.getString("dialerProxy"))
        // The node itself is not changed.
        assertFalse(node.outbound.toString().contains("dialerProxy"))
        // The ping config gets the same chain.
        val probe = JSONObject(XrayConfig.probe(node, fragment = true)).getJSONArray("outbounds").objects()
        assertEquals(listOf("proxy", "fragment"), probe.map { it.getString("tag") })
    }

    @Test
    fun noFragmentForHysteria() {
        val hy = Links.parse("hysteria2://pass@1.2.3.4:443?sni=a.com#h")!!
        val outbounds = JSONObject(XrayConfig.vpn(hy, ruDirect = false, fragment = true)).getJSONArray("outbounds").objects()
        assertFalse(outbounds.any { it.getString("tag") == "fragment" })
    }
}
