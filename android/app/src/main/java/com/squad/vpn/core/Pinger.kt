package com.squad.vpn.core

import com.squad.vpn.App
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.job
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withTimeoutOrNull
import libv2ray.Libv2ray
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/** Real-delay test: an HTTPS request through each node in its own small Xray instance. */
object Pinger {
    const val DEAD = -1L

    /** A result younger than this is not measured again by the background check. */
    const val FRESH_MS = 30 * 60 * 1000L

    /** One node never takes longer than this, even when the core hangs. */
    private const val PING_TIMEOUT_MS = 10_000L

    /**
     * A TCP server that does not accept a connection in this time is dead,
     * no core is started for it. Most dead servers (and on white lists, all
     * servers outside them) are found here in a few seconds.
     */
    private const val CONNECT_TIMEOUT_MS = 3_000

    /** A check of the whole list stops after this; unmeasured nodes keep their old result. */
    const val CHECK_TIMEOUT_MS = 180_000L

    /**
     * The core's call blocks its thread and ignores cancellation, so it runs
     * here and the coroutine only waits for the answer: Stop and the time
     * limits work at once, a hung call just finishes on its own later.
     */
    private val threads = Executors.newCachedThreadPool { task -> Thread(task, "ping").apply { isDaemon = true } }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var check: Job? = null
    /** Keys of the nodes the running check measures. */
    private var checking: Set<String> = emptySet()

    /** The user pressed Stop: the screen does not start a check on its own until they press Check again. */
    @Volatile
    var stoppedByUser = false
        private set

    /** Anti-DPI by hand, or on this network because servers answered only with it. */
    fun autoFragment(): Boolean = Prefs.antiDpi || Prefs.dpiOn(NetworkId.current(App.context))

    suspend fun ping(node: Node, fragment: Boolean = autoFragment()): Long {
        val result = CompletableDeferred<Long>()
        threads.execute {
            result.complete(
                try {
                    if (XrayConfig.overTcp(node) && !accepts(node)) {
                        DEAD
                    } else {
                        val ms = Libv2ray.measureOutboundDelay(XrayConfig.probe(node, fragment), XrayConfig.TEST_URL)
                        if (ms > 0) ms else DEAD
                    }
                } catch (e: Throwable) {
                    DEAD
                },
            )
        }
        return withTimeoutOrNull(PING_TIMEOUT_MS) { result.await() } ?: DEAD
    }

    /** The app is outside its own VPN, so this goes straight from the phone, like the core's own test. */
    private fun accepts(node: Node): Boolean =
        try {
            Socket().use { it.connect(InetSocketAddress(node.server, node.port), CONNECT_TIMEOUT_MS) }
            true
        } catch (e: Exception) {
            false
        }

    /** Pings [nodes] with limited parallelism, publishing each result as it arrives. */
    suspend fun pingAll(
        nodes: List<Node>,
        parallel: Int = 24,
        onEach: () -> Unit = {},
    ): Map<String, Long> = coroutineScope {
        val gate = Semaphore(parallel)
        val fragment = autoFragment()
        nodes.map { node ->
            async {
                gate.withPermit {
                    val ms = ping(node, fragment)
                    Vpn.setPing(node.key, ms)
                    onEach()
                    node.key to ms
                }
            }
        }.awaitAll().toMap()
    }

    /**
     * Checks [nodes] in the background with progress in [Vpn.pingProgress].
     * A check already running is replaced. Join the job to wait for the end.
     */
    @Synchronized
    fun startCheck(nodes: List<Node>, byUser: Boolean = false, timeoutMs: Long = CHECK_TIMEOUT_MS): Job {
        if (byUser) stoppedByUser = false
        check?.cancel()
        checking = nodes.mapTo(HashSet()) { it.key }
        val done = AtomicInteger()
        Vpn.setPingProgress(PingProgress(0, nodes.size))
        val job = scope.launch(start = CoroutineStart.LAZY) {
            val me = coroutineContext.job
            try {
                withTimeoutOrNull(timeoutMs) {
                    pingAll(nodes) { report(me, PingProgress(done.incrementAndGet(), nodes.size)) }
                }
            } finally {
                report(me, null)
            }
        }
        check = job
        job.start()
        return job
    }

    /** A check is running and it measures servers of [nodes] (not of a list shown before). */
    @Synchronized
    fun isChecking(nodes: List<Node>): Boolean {
        if (check == null) return false
        val keys = nodes.mapTo(HashSet()) { it.key }
        return checking.all { it in keys }
    }

    /** Stop button: the screen shows the results measured so far. */
    @Synchronized
    fun stopCheck() {
        stoppedByUser = true
        val job = check ?: return
        check = null
        job.cancel()
        Vpn.setPingProgress(null)
    }

    /** Progress of [job], null at its end. A replaced or stopped check no longer touches the screen. */
    @Synchronized
    private fun report(job: Job, progress: PingProgress?) {
        if (check !== job) return
        if (progress == null) check = null
        Vpn.setPingProgress(progress)
    }
}
