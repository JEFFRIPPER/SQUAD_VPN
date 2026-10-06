package com.squad.vpn.core

import java.io.File
import java.io.IOException
import java.net.Authenticator
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.PasswordAuthentication
import java.net.Proxy
import java.net.URL

/**
 * The app is outside its own VPN, so with the VPN on a request goes either
 * straight out or through Xray's local SOCKS port. In white-list mode only
 * the second works, so when connected both are tried.
 */
object Http {
    private val socks = Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", XrayConfig.SOCKS_PORT))

    init {
        // Java's SOCKS client takes the password of the core's port from here.
        Authenticator.setDefault(object : Authenticator() {
            override fun getPasswordAuthentication(): PasswordAuthentication? =
                if (requestingProtocol == "SOCKS5" && requestingPort == XrayConfig.SOCKS_PORT) {
                    PasswordAuthentication(XrayConfig.socksUser, XrayConfig.socksPass.toCharArray())
                } else {
                    null
                }
        })
    }

    /** Null when the core's SOCKS port lets this app through, else why not. */
    fun socksProblem(url: String = XrayConfig.TEST_URL): String? =
        try {
            val conn = open(url, socks, 10_000)
            try {
                conn.responseCode
                null
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            e.message ?: e.javaClass.simpleName
        }

    private fun routes(): List<Proxy> =
        if (Vpn.isConnected) listOf(socks, Proxy.NO_PROXY) else listOf(Proxy.NO_PROXY)

    private fun open(url: String, proxy: Proxy, timeoutMs: Int): HttpURLConnection =
        (URL(url).openConnection(proxy) as HttpURLConnection).apply {
            connectTimeout = timeoutMs
            readTimeout = timeoutMs
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", "SQUAD-VPN-Android")
        }

    fun getText(urls: List<String>, timeoutMs: Int = 15_000): String {
        var last: Exception = IOException("нет адресов")
        for (url in urls) for (proxy in routes()) {
            try {
                val conn = open(url, proxy, timeoutMs)
                try {
                    if (conn.responseCode !in 200..299) throw IOException("HTTP ${conn.responseCode}")
                    return conn.inputStream.bufferedReader().use { it.readText() }
                } finally {
                    conn.disconnect()
                }
            } catch (e: Exception) {
                last = e
            }
        }
        throw last
    }

    /**
     * A JSON API call (GitHub). Returns the status and body; throws only when
     * no route reached the server at all.
     */
    fun call(method: String, url: String, body: String?, headers: Map<String, String>, timeoutMs: Int = 20_000): Pair<Int, String> {
        var last: Exception = IOException("нет адреса")
        for (proxy in routes()) {
            try {
                val conn = open(url, proxy, timeoutMs)
                try {
                    conn.requestMethod = method
                    headers.forEach { (key, value) -> conn.setRequestProperty(key, value) }
                    if (body != null) {
                        conn.doOutput = true
                        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                        conn.outputStream.use { it.write(body.toByteArray()) }
                    }
                    val code = conn.responseCode
                    val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                    return code to (stream?.bufferedReader()?.use { it.readText() } ?: "")
                } finally {
                    conn.disconnect()
                }
            } catch (e: Exception) {
                last = e
            }
        }
        throw last
    }

    /** Does [url] answer straight from this phone's network, never through the VPN? */
    fun reachableDirect(url: String, timeoutMs: Int = 6_000): Boolean =
        try {
            val conn = open(url, Proxy.NO_PROXY, timeoutMs)
            try {
                conn.requestMethod = "HEAD"
                conn.responseCode in 200..399
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            false
        }

    fun download(url: String, target: File, progress: (Long, Long) -> Unit) {
        var last: Exception = IOException("нет адреса")
        for (proxy in routes()) {
            try {
                val conn = open(url, proxy, 30_000)
                try {
                    if (conn.responseCode !in 200..299) throw IOException("HTTP ${conn.responseCode}")
                    val total = conn.contentLengthLong
                    target.parentFile?.mkdirs()
                    conn.inputStream.use { input ->
                        target.outputStream().use { output ->
                            val buffer = ByteArray(64 * 1024)
                            var done = 0L
                            while (true) {
                                val n = input.read(buffer)
                                if (n < 0) break
                                output.write(buffer, 0, n)
                                done += n
                                progress(done, total)
                            }
                        }
                    }
                    return
                } finally {
                    conn.disconnect()
                }
            } catch (e: Exception) {
                last = e
            }
        }
        throw last
    }
}
