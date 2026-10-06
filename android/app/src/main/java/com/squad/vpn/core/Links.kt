package com.squad.vpn.core

import org.json.JSONArray
import org.json.JSONObject
import java.net.URLDecoder
import java.security.MessageDigest
import java.util.Base64

/** One server from a subscription, already turned into an Xray outbound (without a tag). */
data class Node(
    val name: String,
    val protocol: String,
    val server: String,
    val port: Int,
    val outbound: JSONObject,
    /** The subscription line this node came from (for the phone probe). */
    val link: String = "",
) {
    /** Same server and settings => same key, so pings survive a subscription refresh. */
    val key: String get() = "$protocol://$server:$port#${outbound.toString().hashCode()}"
}

/**
 * Share links (vless/vmess/trojan/ss/hysteria2) -> Xray outbounds, the same
 * shape v2rayNG writes. Links Xray cannot serve (unknown transports, ss
 * plugins…) are skipped instead of producing a broken node.
 */
object Links {
    fun parseSubscription(text: String): List<Node> {
        val nodes = mutableListOf<Node>()
        val used = HashMap<String, Int>()
        val keys = HashSet<String>()
        for (raw in decodeBody(text).lineSequence()) {
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#")) continue
            val node = runCatching { parse(line) }.getOrNull()?.copy(link = line) ?: continue
            if (!keys.add(node.key)) continue
            val count = (used[node.name] ?: 0) + 1
            used[node.name] = count
            nodes += if (count == 1) node else node.copy(name = "${node.name} · $count")
        }
        return nodes
    }

    /** Subscriptions come either as plain lines or as one base64 blob. */
    fun decodeBody(text: String): String {
        val trimmed = text.trim().removePrefix("﻿")
        if (trimmed.contains("://")) return trimmed
        return runCatching { String(decodeBase64(trimmed.replace(Regex("\\s"), "")), Charsets.UTF_8) }
            .getOrDefault(trimmed)
    }

    fun parse(link: String): Node? = when (link.substringBefore("://").lowercase()) {
        "vless" -> vless(Parts.of(link))
        "vmess" -> vmess(link)
        "trojan" -> trojan(Parts.of(link))
        "ss" -> shadowsocks(link)
        "hysteria2", "hy2" -> hysteria2(Parts.of(link))
        else -> null
    }

    private class Parts(
        val user: String,
        val host: String,
        val port: Int,
        val query: Map<String, String>,
        val name: String,
    ) {
        fun q(key: String): String = query[key].orEmpty()

        companion object {
            fun of(link: String): Parts {
                val rest = link.substringBefore('#').substringAfter("://")
                val authority = rest.substringBefore('?').substringBefore('/')
                val hostPort = authority.substringAfterLast('@')
                val host: String
                val port: Int
                if (hostPort.startsWith("[")) {
                    host = hostPort.substringAfter('[').substringBefore(']')
                    port = hostPort.substringAfter("]:", "").toIntOrNull() ?: 443
                } else {
                    host = hostPort.substringBeforeLast(':')
                    port = hostPort.substringAfterLast(':', "").toIntOrNull() ?: 443
                }
                return Parts(
                    user = decode(authority.substringBeforeLast('@', "")),
                    host = host,
                    port = port,
                    query = parseQuery(rest.substringAfter('?', "")),
                    name = decode(link.substringAfter('#', "")).trim(),
                )
            }
        }
    }

    private fun vless(p: Parts): Node? {
        if (p.user.isEmpty() || p.host.isEmpty()) return null
        val settings = server(p).put("id", p.user).put("encryption", p.q("encryption").ifEmpty { "none" })
        val flow = p.q("flow")
        if (flow.isNotEmpty()) settings.put("flow", flow)
        val stream = stream(p, p.q("security")) ?: return null
        return node("vless", p, settings, stream)
    }

    private fun trojan(p: Parts): Node? {
        if (p.user.isEmpty() || p.host.isEmpty()) return null
        val settings = server(p).put("password", p.user)
        val stream = stream(p, p.q("security").ifEmpty { "tls" }) ?: return null
        return node("trojan", p, settings, stream)
    }

    private fun vmess(link: String): Node? {
        val json = JSONObject(String(decodeBase64(link.substringAfter("://").substringBefore('#')), Charsets.UTF_8))
        val host = json.optString("add").trim()
        val id = json.optString("id").trim()
        if (host.isEmpty() || id.isEmpty()) return null
        val net = json.optString("net").ifEmpty { "tcp" }
        val query = hashMapOf(
            "type" to net,
            "headerType" to json.optString("type"),
            "host" to json.optString("host"),
            "path" to json.optString("path"),
            "serviceName" to json.optString("path"),
            "sni" to json.optString("sni"),
            "alpn" to json.optString("alpn"),
            "fp" to json.optString("fp"),
                    )
        if (net == "grpc" && json.optString("type") == "multi") query["mode"] = "multi"
        val p = Parts(
            user = id,
            host = host,
            port = json.optString("port").trim().toIntOrNull() ?: 443,
            query = query,
            name = json.optString("ps").trim(),
        )
        val settings = server(p)
            .put("id", id)
            .put("security", json.optString("scy").ifEmpty { "auto" })
        val security = json.optString("tls").takeIf { it == "tls" || it == "reality" }.orEmpty()
        val stream = stream(p, security) ?: return null
        return node("vmess", p, settings, stream)
    }

    private fun shadowsocks(link: String): Node? {
        val name = decode(link.substringAfter('#', "")).trim()
        var rest = link.substringBefore('#').substringAfter("://")
        val query = parseQuery(rest.substringAfter('?', ""))
        rest = rest.substringBefore('?').trimEnd('/')
        val plugin = query["plugin"].orEmpty()
        if (plugin.isNotEmpty() && plugin != "none") return null
        val userInfo: String
        val hostPort: String
        if (rest.contains('@')) {
            val encoded = decode(rest.substringBeforeLast('@'))
            userInfo = if (encoded.contains(':')) encoded else String(decodeBase64(encoded), Charsets.UTF_8)
            hostPort = rest.substringAfterLast('@')
        } else {
            val decoded = String(decodeBase64(rest), Charsets.UTF_8)
            userInfo = decoded.substringBeforeLast('@')
            hostPort = decoded.substringAfterLast('@')
        }
        val method = userInfo.substringBefore(':')
        val password = userInfo.substringAfter(':', "")
        val host = hostPort.substringBeforeLast(':').trim('[', ']')
        val port = hostPort.substringAfterLast(':').toIntOrNull() ?: return null
        if (method.isEmpty() || host.isEmpty()) return null
        val p = Parts("", host, port, emptyMap(), name)
        val settings = server(p).put("method", method).put("password", password)
        return node("shadowsocks", p, settings, JSONObject().put("network", "raw"))
    }

    private fun hysteria2(p: Parts): Node? {
        if (p.host.isEmpty()) return null
        val settings = server(p).put("version", 2)
        val stream = JSONObject()
            .put("network", "hysteria")
            .put("hysteriaSettings", JSONObject().put("version", 2).put("auth", p.user))
        val obfsPassword = p.q("obfs-password")
        if (p.q("obfs") == "salamander" && obfsPassword.isNotEmpty()) {
            val mask = JSONObject().put("type", "salamander").put("settings", JSONObject().put("password", obfsPassword))
            stream.put("finalmask", JSONObject().put("udp", JSONArray().put(mask)))
        }
        val tls = JSONObject()
            .put("serverName", p.q("sni").ifEmpty { p.host })
            .put("alpn", JSONArray().put("h3"))
        pins(p, tls)
        stream.put("security", "tls").put("tlsSettings", tls)
        return node("hysteria", p, settings, stream)
    }

    private fun server(p: Parts): JSONObject =
        JSONObject().put("address", p.host).put("port", p.port).put("level", 8)

    private fun node(protocol: String, p: Parts, settings: JSONObject, stream: JSONObject): Node {
        val outbound = JSONObject()
            .put("protocol", protocol)
            .put("settings", settings)
            .put("streamSettings", stream)
        val label = if (protocol == "hysteria") "hysteria2" else protocol
        return Node(cleanName(p.name, p.host), label, p.host, p.port, outbound)
    }

    private fun cleanName(name: String, host: String): String =
        name.replace(Regex("\\p{Cntrl}"), " ").trim().ifEmpty { host }.take(64)

    // Xray dropped allowInsecure: "insecure" links are checked normally (a
    // self-signed server then fails its ping and is skipped), pinned ones
    // keep their pin.
    private fun pins(p: Parts, tls: JSONObject) {
        val pin = p.q("pcs").ifEmpty { p.q("pinSHA256") }.replace(":", "").lowercase()
        if (Regex("[0-9a-f]{64}(,[0-9a-f]{64})*").matches(pin)) tls.put("pinnedPeerCertSha256", pin)
        p.q("vcn").takeIf { it.isNotEmpty() }?.let { tls.put("verifyPeerCertByName", it) }
    }

    private fun list(value: String): JSONArray? {
        val items = value.split(',').map { it.trim() }.filter { it.isNotEmpty() }
        return if (items.isEmpty()) null else JSONArray(items)
    }

    /** streamSettings for vless/vmess/trojan; null when the transport is unknown. */
    private fun stream(p: Parts, security: String): JSONObject? {
        val stream = JSONObject()
        val host = p.q("host")
        val path = p.q("path")
        var sniFromTransport = host
        when (val network = p.q("type").ifEmpty { "tcp" }) {
            "tcp", "raw" -> {
                stream.put("network", "raw")
                if (p.q("headerType") == "http") {
                    val request = JSONObject().put("path", list(path) ?: JSONArray().put("/"))
                    list(host)?.let { request.put("headers", JSONObject().put("Host", it)) }
                    stream.put(
                        "rawSettings",
                        JSONObject().put("header", JSONObject().put("type", "http").put("request", request)),
                    )
                    sniFromTransport = host.substringBefore(',')
                }
            }
            "ws", "httpupgrade" -> {
                stream.put("network", network)
                val settings = JSONObject().put("path", path.ifEmpty { "/" })
                if (host.isNotEmpty()) settings.put("host", host)
                stream.put(if (network == "ws") "wsSettings" else "httpupgradeSettings", settings)
            }
            "xhttp", "splithttp", "h2", "http" -> {
                stream.put("network", "xhttp")
                val settings = JSONObject().put("path", path.ifEmpty { "/" })
                if (host.isNotEmpty()) settings.put("host", host.substringBefore(','))
                p.q("mode").takeIf { it.isNotEmpty() }?.let { settings.put("mode", it) }
                val extra = p.q("extra")
                if (extra.startsWith("{")) runCatching { settings.put("extra", JSONObject(extra)) }
                stream.put("xhttpSettings", settings)
                sniFromTransport = host.substringBefore(',')
            }
            "grpc" -> {
                stream.put("network", "grpc")
                val settings = JSONObject()
                    .put("serviceName", p.q("serviceName").ifEmpty { p.q("service_name") })
                    .put("multiMode", p.q("mode") == "multi")
                val authority = p.q("authority")
                if (authority.isNotEmpty()) settings.put("authority", authority)
                stream.put("grpcSettings", settings)
                sniFromTransport = authority
            }
            else -> return null
        }

        when (security) {
            "tls", "xtls" -> {
                val tls = JSONObject()
                val sni = p.q("sni").ifEmpty { p.q("peer") }.ifEmpty {
                    sniFromTransport.takeIf { isDomain(it) } ?: p.host.takeIf { isDomain(it) }.orEmpty()
                }
                if (sni.isNotEmpty()) tls.put("serverName", sni)
                pins(p, tls)
                list(p.q("alpn"))?.let { tls.put("alpn", it) }
                p.q("fp").takeIf { it.isNotEmpty() }?.let { tls.put("fingerprint", it) }
                p.q("ech").takeIf { it.isNotEmpty() }?.let { tls.put("echConfigList", it) }
                stream.put("security", "tls").put("tlsSettings", tls)
            }
            "reality" -> {
                val key = p.q("pbk")
                if (key.isEmpty()) return null
                val reality = JSONObject()
                    .put("serverName", p.q("sni"))
                    .put("fingerprint", p.q("fp").ifEmpty { "chrome" })
                    .put("publicKey", key)
                    .put("shortId", p.q("sid"))
                p.q("spx").takeIf { it.isNotEmpty() }?.let { reality.put("spiderX", it) }
                p.q("pqv").takeIf { it.isNotEmpty() }?.let { reality.put("mldsa65Verify", it) }
                stream.put("security", "reality").put("realitySettings", reality)
            }
            "", "none" -> {}
            else -> return null
        }
        return stream
    }

    private fun isDomain(value: String): Boolean =
        value.isNotEmpty() && !value.contains(':') && !value.all { it.isDigit() || it == '.' }

    private fun parseQuery(query: String): Map<String, String> {
        if (query.isEmpty()) return emptyMap()
        val map = HashMap<String, String>()
        for (pair in query.split('&')) {
            if (pair.isEmpty()) continue
            val key = decode(pair.substringBefore('='))
            if (key !in map) map[key] = decode(pair.substringAfter('=', ""))
        }
        return map
    }

    private fun decode(value: String): String =
        runCatching { URLDecoder.decode(value.replace("+", "%2B"), "UTF-8") }.getOrDefault(value)

    /** Key of a subscription line without its display name: link_key() in src/squad_vpn/smart.py. */
    fun linkKey(link: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(link.trim().substringBefore('#').toByteArray())
        return digest.joinToString("") { "%02x".format(it) }.take(16)
    }

    fun decodeBase64(value: String): ByteArray {
        val clean = value.trim().replace('-', '+').replace('_', '/').trimEnd('=')
        val padded = clean + "=".repeat((4 - clean.length % 4) % 4)
        return Base64.getDecoder().decode(padded)
    }
}
