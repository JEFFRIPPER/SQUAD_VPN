package com.squad.vpn.core

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class Status { Disconnected, Connecting, Connected, Disconnecting, Failed }

data class Traffic(
    val downBps: Long = 0,
    val upBps: Long = 0,
    val downTotal: Long = 0,
    val upTotal: Long = 0,
    /** Last minute of download speed, oldest first, for the sparkline. */
    val history: List<Long> = emptyList(),
)

/** Process-wide VPN state shared by the service and the UI. */
object Vpn {
    private val _status = MutableStateFlow(Status.Disconnected)
    val status: StateFlow<Status> = _status.asStateFlow()

    private val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message.asStateFlow()

    private val _current = MutableStateFlow<Node?>(null)
    val current: StateFlow<Node?> = _current.asStateFlow()

    private val _ping = MutableStateFlow<Long?>(null)
    val ping: StateFlow<Long?> = _ping.asStateFlow()

    private val _since = MutableStateFlow(0L)
    val since: StateFlow<Long> = _since.asStateFlow()

    private val _traffic = MutableStateFlow(Traffic())
    val traffic: StateFlow<Traffic> = _traffic.asStateFlow()

    private val _nodes = MutableStateFlow<List<Node>>(emptyList())
    val nodes: StateFlow<List<Node>> = _nodes.asStateFlow()

    private val _pings = MutableStateFlow<Map<String, Long>>(emptyMap())
    val pings: StateFlow<Map<String, Long>> = _pings.asStateFlow()

    /** When each ping in [pings] was measured (ms since epoch), for [PingStore]. */
    private val pingTimes = java.util.concurrent.ConcurrentHashMap<String, Long>()

    private val _pinging = MutableStateFlow(false)
    val pinging: StateFlow<Boolean> = _pinging.asStateFlow()

    private val _events = MutableStateFlow<List<String>>(emptyList())
    val events: StateFlow<List<String>> = _events.asStateFlow()

    val isConnected: Boolean get() = _status.value == Status.Connected

    fun setStatus(status: Status, message: String? = null) {
        _status.value = status
        _message.value = message
        when (status) {
            Status.Connected -> if (_since.value == 0L) _since.value = System.currentTimeMillis()
            Status.Disconnected, Status.Failed -> {
                _since.value = 0L
                _ping.value = null
                _traffic.value = Traffic()
                _current.value = null
            }
            else -> {}
        }
    }

    fun setCurrent(node: Node?) {
        _current.value = node
    }

    fun setPingNow(ms: Long?) {
        _ping.value = ms
    }

    fun setNodes(nodes: List<Node>) {
        _nodes.value = nodes
    }

    fun setPing(key: String, ms: Long) {
        pingTimes[key] = System.currentTimeMillis()
        _pings.update { it + (key to ms) }
    }

    /** Results saved by an earlier run: key to (ping, measured at). Newer results win. */
    fun restorePings(saved: Map<String, Pair<Long, Long>>) {
        _pings.update { current ->
            val restored = saved.filterKeys { it !in current }
            restored.forEach { (key, value) -> pingTimes[key] = value.second }
            restored.mapValues { it.value.first } + current
        }
    }

    /** [key] has a result measured less than [maxAgeMs] ago. */
    fun isFresh(key: String, maxAgeMs: Long = Pinger.FRESH_MS): Boolean =
        key in _pings.value && System.currentTimeMillis() - (pingTimes[key] ?: 0L) < maxAgeMs

    fun pingsWithTimes(): Map<String, Pair<Long, Long>> =
        _pings.value.mapValues { (key, ms) -> ms to (pingTimes[key] ?: 0L) }

    /**
     * Another network (Wi-Fi vs mobile, another operator) may reach other
     * nodes: forget which ones looked dead, keep the known-alive ones.
     */
    fun forgetDead() {
        _pings.update { pings -> pings.filterValues { it > 0 } }
    }

    fun setPinging(value: Boolean) {
        _pinging.value = value
    }

    fun addTraffic(down: Long, up: Long, seconds: Double) {
        _traffic.update {
            val downBps = (down / seconds).toLong()
            Traffic(
                downBps = downBps,
                upBps = (up / seconds).toLong(),
                downTotal = it.downTotal + down,
                upTotal = it.upTotal + up,
                history = (it.history + downBps).takeLast(30),
            )
        }
    }

    fun event(text: String) {
        val time = SimpleDateFormat("HH:mm:ss", Locale.ROOT).format(Date())
        _events.update { (listOf("$time  $text") + it).take(40) }
    }
}
