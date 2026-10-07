package com.squad.vpn.core

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.IOException
import kotlin.coroutines.coroutineContext

sealed interface SpeedState {
    data object Idle : SpeedState
    data class Running(val mbps: Double) : SpeedState
    data class Done(val mbps: Double, val server: String) : SpeedState
    data class Error(val message: String) : SpeedState
}

/** Download speed through the connected server: one file over the core's SOCKS port. */
object SpeedTest {
    private const val URL = "https://speed.cloudflare.com/__down?bytes=$MAX_BYTES"

    /** Caps the traffic one test costs on mobile data. */
    const val MAX_BYTES = 40_000_000L
    private const val LIMIT_MS = 8_000L

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null
    private val _state = MutableStateFlow<SpeedState>(SpeedState.Idle)
    val state: StateFlow<SpeedState> = _state.asStateFlow()

    @Synchronized
    fun start() {
        if (job?.isActive == true) return
        if (!Vpn.isConnected) {
            _state.value = SpeedState.Error("Сначала подключи VPN")
            return
        }
        val server = Vpn.current.value?.name ?: ""
        _state.value = SpeedState.Running(0.0)
        job = scope.launch {
            val me = coroutineContext.job
            val result = try {
                SpeedState.Done(measure(me), server)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                SpeedState.Error("Не получилось: ${e.message ?: e.javaClass.simpleName}")
            }
            publish(me, result)
        }
    }

    @Synchronized
    fun stop() {
        job?.cancel()
        job = null
        _state.value = SpeedState.Idle
    }

    /** A stopped test finishing its last read no longer touches the screen. */
    @Synchronized
    private fun publish(from: Job, value: SpeedState) {
        if (job === from) _state.value = value
    }

    private suspend fun measure(me: Job): Double {
        val conn = Http.openViaVpn(URL)
        try {
            if (conn.responseCode !in 200..299) throw IOException("HTTP ${conn.responseCode}")
            // Counted from the first byte: the handshake is the ping's business, not the speed's.
            val buffer = ByteArray(64 * 1024)
            var bytes = 0L
            var started = 0L
            var shown = 0L
            conn.inputStream.use { input ->
                while (true) {
                    coroutineContext.ensureActive()
                    val n = input.read(buffer)
                    if (n < 0) break
                    val now = System.nanoTime()
                    if (started == 0L) {
                        started = now
                        continue
                    }
                    bytes += n
                    val ms = (now - started) / 1_000_000
                    if (ms - shown >= 250) {
                        shown = ms
                        publish(me, SpeedState.Running(mbps(bytes, ms)))
                    }
                    if (ms >= LIMIT_MS) break
                }
            }
            if (started == 0L) throw IOException("пустой ответ")
            return mbps(bytes, (System.nanoTime() - started) / 1_000_000)
        } finally {
            conn.disconnect()
        }
    }

    internal fun mbps(bytes: Long, ms: Long): Double = if (ms <= 0) 0.0 else bytes * 8.0 / ms / 1000.0
}
