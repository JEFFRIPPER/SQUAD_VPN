package com.squad.vpn.core

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Pings measured on this phone outlive the app: the next start (or the next
 * connect) already knows which nodes answer here, on this operator, and
 * tries them first. Answers are kept for [MAX_AGE_MS]; "no answer" only for
 * [DEAD_AGE_MS], since the phone may be on another network by then.
 */
object PingStore {
    private const val MAX_AGE_MS = 12 * 60 * 60 * 1000L
    private const val DEAD_AGE_MS = 60 * 60 * 1000L
    private lateinit var file: File

    @OptIn(FlowPreview::class)
    fun init(context: Context) {
        file = File(context.filesDir, "pings.json")
        Vpn.restorePings(load())
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            Vpn.pings.drop(1).debounce(3_000).collect { save() }
        }
        watchNetwork(context)
    }

    /**
     * Wi-Fi <-> mobile or another SIM: nodes that did not answer may answer
     * now. The app stays outside its own VPN, so this is the real network.
     */
    private fun watchNetwork(context: Context) {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        var last: Network? = cm.activeNetwork
        runCatching {
            cm.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    if (network == last) return
                    val changed = last != null
                    last = network
                    if (changed) Vpn.forgetDead()
                }
            })
        }
    }

    private fun load(): Map<String, Pair<Long, Long>> = runCatching {
        val now = System.currentTimeMillis()
        val json = JSONObject(file.readText())
        buildMap {
            for (key in json.keys()) {
                val entry = json.getJSONArray(key)
                val ms = entry.getLong(0)
                val at = entry.getLong(1)
                val maxAge = if (ms > 0) MAX_AGE_MS else DEAD_AGE_MS
                if (now - at in 0..maxAge) put(key, ms to at)
            }
        }
    }.getOrDefault(emptyMap())

    private fun save() {
        val json = JSONObject()
        Vpn.pingsWithTimes().forEach { (key, value) ->
            json.put(key, JSONArray().put(value.first).put(value.second))
        }
        runCatching {
            val tmp = File(file.path + ".tmp")
            tmp.writeText(json.toString())
            tmp.renameTo(file)
        }
    }
}
