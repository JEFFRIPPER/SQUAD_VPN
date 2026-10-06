package com.squad.vpn.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class LinksTest {
    private fun b64(text: String): String = Base64.getEncoder().encodeToString(text.toByteArray())

    private fun parse(link: String): Node = Links.parse(link) ?: throw AssertionError("not parsed: $link")

    private val Node.settings: JSONObject get() = outbound.getJSONObject("settings")
    private val Node.stream: JSONObject get() = outbound.getJSONObject("streamSettings")

    @Test
    fun vlessReality() {
        val node = parse(
            "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443" +
                "?security=reality&pbk=PUBKEY&sid=ab12&sni=www.microsoft.com&fp=firefox&flow=xtls-rprx-vision&type=tcp" +
                "#%F0%9F%87%B3%F0%9F%87%B1%20NL%201",
        )
        assertEquals("vless", node.protocol)
        assertEquals("1.2.3.4", node.server)
        assertEquals(443, node.port)
        assertEquals("🇳🇱 NL 1", node.name)
        assertEquals("11111111-2222-3333-4444-555555555555", node.settings.getString("id"))
        assertEquals("none", node.settings.getString("encryption"))
        assertEquals("xtls-rprx-vision", node.settings.getString("flow"))
        assertEquals("raw", node.stream.getString("network"))
        assertEquals("reality", node.stream.getString("security"))
        val reality = node.stream.getJSONObject("realitySettings")
        assertEquals("PUBKEY", reality.getString("publicKey"))
        assertEquals("ab12", reality.getString("shortId"))
        assertEquals("www.microsoft.com", reality.getString("serverName"))
        assertEquals("firefox", reality.getString("fingerprint"))
    }

    @Test
    fun realityWithoutPublicKeyIsSkipped() {
        assertNull(Links.parse("vless://id@1.2.3.4:443?security=reality&sni=a.com#x"))
    }

    @Test
    fun vlessWebSocketTakesSniFromHost() {
        val node = parse("vless://id@1.2.3.4:8443?type=ws&security=tls&host=cdn.example.com&path=%2Fws%3Fed%3D2048#ws")
        assertEquals(8443, node.port)
        assertEquals("ws", node.stream.getString("network"))
        val ws = node.stream.getJSONObject("wsSettings")
        assertEquals("/ws?ed=2048", ws.getString("path"))
        assertEquals("cdn.example.com", ws.getString("host"))
        assertEquals("cdn.example.com", node.stream.getJSONObject("tlsSettings").getString("serverName"))
    }

    @Test
    fun tlsWithoutDomainHasNoServerName() {
        val node = parse("vless://id@1.2.3.4:443?security=tls#ip")
        assertFalse(node.stream.getJSONObject("tlsSettings").has("serverName"))
    }

    @Test
    fun vlessXhttp() {
        val node = parse("vless://id@example.com:443?type=xhttp&security=tls&path=%2Fx&host=a.com,b.com&mode=packet-up#x")
        assertEquals("xhttp", node.stream.getString("network"))
        val xhttp = node.stream.getJSONObject("xhttpSettings")
        assertEquals("/x", xhttp.getString("path"))
        assertEquals("a.com", xhttp.getString("host"))
        assertEquals("packet-up", xhttp.getString("mode"))
    }

    @Test
    fun grpc() {
        val node = parse("vless://id@example.com:443?type=grpc&serviceName=svc&mode=multi&security=tls#g")
        val grpc = node.stream.getJSONObject("grpcSettings")
        assertEquals("svc", grpc.getString("serviceName"))
        assertTrue(grpc.getBoolean("multiMode"))
    }

    @Test
    fun unknownTransportOrSecurityIsSkipped() {
        assertNull(Links.parse("vless://id@1.2.3.4:443?type=kcp#kcp"))
        assertNull(Links.parse("vless://id@1.2.3.4:443?security=weird#w"))
        assertNull(Links.parse("vless://@1.2.3.4:443#no-id"))
        assertNull(Links.parse("socks://1.2.3.4:1080"))
    }

    @Test
    fun ipv6Host() {
        val node = parse("vless://id@[2001:db8::1]:8443?security=none#v6")
        assertEquals("2001:db8::1", node.server)
        assertEquals(8443, node.port)
    }

    @Test
    fun missingPortMeans443() {
        assertEquals(443, parse("trojan://pass@example.com#t").port)
    }

    @Test
    fun vmess() {
        val json = """{"v":"2","ps":"VM 1","add":"vm.example.com","port":"2053","id":"uuid-1","aid":"0",""" +
            """"scy":"auto","net":"ws","type":"none","host":"h.example.com","path":"/p","tls":"tls","sni":"s.example.com"}"""
        val node = parse("vmess://" + b64(json))
        assertEquals("vmess", node.protocol)
        assertEquals("VM 1", node.name)
        assertEquals(2053, node.port)
        assertEquals("uuid-1", node.settings.getString("id"))
        assertEquals("ws", node.stream.getString("network"))
        assertEquals("/p", node.stream.getJSONObject("wsSettings").getString("path"))
        assertEquals("s.example.com", node.stream.getJSONObject("tlsSettings").getString("serverName"))
    }

    @Test
    fun trojanDefaultsToTlsAndKeepsPlus() {
        val node = parse("trojan://a+b@example.com:443?sni=example.com#%D0%A1%D0%B5%D1%80%D0%B2%D0%B5%D1%80")
        assertEquals("a+b", node.settings.getString("password"))
        assertEquals("tls", node.stream.getString("security"))
        assertEquals("Сервер", node.name)
    }

    @Test
    fun shadowsocks() {
        val sip002 = parse("ss://" + b64("chacha20-ietf-poly1305:secret") + "@5.6.7.8:8388#ss")
        assertEquals("shadowsocks", sip002.protocol)
        assertEquals("chacha20-ietf-poly1305", sip002.settings.getString("method"))
        assertEquals("secret", sip002.settings.getString("password"))
        assertEquals(8388, sip002.port)

        val legacy = parse("ss://" + b64("aes-256-gcm:pw@5.6.7.8:443") + "#old")
        assertEquals("aes-256-gcm", legacy.settings.getString("method"))
        assertEquals("5.6.7.8", legacy.server)

        assertNull(Links.parse("ss://" + b64("aes-256-gcm:pw") + "@5.6.7.8:443?plugin=obfs-local#p"))
    }

    @Test
    fun hysteria2WithObfs() {
        val node = parse("hy2://auth@example.com:443?sni=sni.example.com&obfs=salamander&obfs-password=pw#hy")
        assertEquals("hysteria2", node.protocol)
        assertEquals("hysteria", node.outbound.getString("protocol"))
        assertEquals("auth", node.stream.getJSONObject("hysteriaSettings").getString("auth"))
        assertEquals("sni.example.com", node.stream.getJSONObject("tlsSettings").getString("serverName"))
        val mask = node.stream.getJSONObject("finalmask").getJSONArray("udp").getJSONObject(0)
        assertEquals("salamander", mask.getString("type"))
    }

    @Test
    fun certificatePin() {
        val pin = "AB".repeat(32)
        val node = parse("trojan://p@example.com:443?pcs=$pin#pin")
        assertEquals(pin.lowercase(), node.stream.getJSONObject("tlsSettings").getString("pinnedPeerCertSha256"))
    }

    @Test
    fun nameFallsBackToHostAndIsCleaned() {
        assertEquals("example.com", parse("trojan://p@example.com:443").name)
        assertEquals("a b", parse("trojan://p@example.com:443#a%0Ab").name)
        assertEquals(64, parse("trojan://p@example.com:443#" + "x".repeat(100)).name.length)
    }

    @Test
    fun subscriptionAsBase64WithDuplicates() {
        val lines = listOf(
            "# comment",
            "trojan://p1@a.example.com:443#Same",
            "trojan://p2@b.example.com:443#Same",
            "trojan://p1@a.example.com:443#Same",
            "unknown://whatever",
            "",
            "vless://id@1.2.3.4:443?type=kcp#bad",
        )
        val nodes = Links.parseSubscription(b64(lines.joinToString("\n")))
        assertEquals(listOf("Same", "Same · 2"), nodes.map { it.name })
    }

    @Test
    fun plainSubscriptionAndUrlSafeBase64() {
        assertEquals(1, Links.parseSubscription("﻿trojan://p@a.example.com:443#x\n").size)
        val urlSafe = Base64.getUrlEncoder().withoutPadding().encodeToString("trojan://p@a.example.com:443#x??".toByteArray())
        assertEquals("trojan://p@a.example.com:443#x??", String(Links.decodeBase64(urlSafe)))
    }

    @Test
    fun keyIsStableAndDependsOnSettings() {
        val a = parse("trojan://p@example.com:443#a")
        assertEquals(a.key, parse("trojan://p@example.com:443#other name").key)
        assertFalse(a.key == parse("trojan://q@example.com:443#a").key)
    }
}
