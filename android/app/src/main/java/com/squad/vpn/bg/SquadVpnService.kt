package com.squad.vpn.bg

import android.app.Notification
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.squad.vpn.App
import com.squad.vpn.R
import com.squad.vpn.core.DirectApps
import com.squad.vpn.core.Http
import com.squad.vpn.core.NetworkId
import com.squad.vpn.core.Node
import com.squad.vpn.core.PhoneProbe
import com.squad.vpn.core.Pinger
import com.squad.vpn.core.Prefs
import com.squad.vpn.core.Profile
import com.squad.vpn.core.Status
import com.squad.vpn.core.Subscriptions
import com.squad.vpn.core.Vpn
import com.squad.vpn.core.XrayConfig
import com.squad.vpn.ui.MainActivity
import com.squad.vpn.ui.formatSpeed
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import libv2ray.CoreCallbackHandler
import libv2ray.CoreController
import libv2ray.Libv2ray

/**
 * The VPN: Android hands us a TUN interface, Xray reads it directly
 * (its own tun inbound) and sends everything through one node.
 *
 * Like the Windows client it watches that node: every 15 s it pings through
 * the running core, and after two misses in a row it moves to the next best
 * node without dropping the VPN interface.
 */
class SquadVpnService : VpnService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val lock = Mutex()
    private var tun: ParcelFileDescriptor? = null
    private var monitor: Job? = null
    private var connecting: Job? = null
    /** A server switch or failover asked from outside: Disconnect cancels it. */
    private var switching: Job? = null

    /** The user wants the VPN on; a stop that is still finishing must not undo a newer start. */
    @Volatile
    private var wanted = false
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var candidates: List<Node> = emptyList()
    /** [NetworkId] of the network the VPN runs over now. */
    @Volatile
    private var netId = ""
    private val failed = mutableSetOf<String>()

    private val core: CoreController by lazy {
        Libv2ray.newCoreController(object : CoreCallbackHandler {
            override fun startup(): Long = 0
            override fun shutdown(): Long = 0
            override fun onEmitStatus(code: Long, message: String?): Long {
                Log.i(TAG, "core: $message")
                return 0
            }
        })
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stop("Отключено")
            ACTION_SWITCH -> switching = scope.launch { switchTo(Prefs.selectedNode, "выбран вручную") }
            ACTION_FAILOVER -> switching = scope.launch { failover("сменить сервер") }
            ACTION_RELOAD_APPS -> scope.launch { reloadApps() }
            // ACTION_START, always-on VPN (SERVICE_INTERFACE) and a restart by the system.
            else -> start()
        }
        return START_STICKY
    }

    override fun onRevoke() {
        stop("Другое VPN-приложение забрало подключение")
    }

    override fun onDestroy() {
        scope.cancel()
        unwatchNetwork()
        runCatching { core.stopLoop() }
        tun?.close()
        tun = null
        if (Vpn.status.value != Status.Failed) Vpn.setStatus(Status.Disconnected)
        super.onDestroy()
    }

    private fun start() {
        // Always answer startForegroundService() with startForeground(), even when already running.
        val running = Vpn.status.value == Status.Connected || Vpn.status.value == Status.Connecting
        foreground(notification(Vpn.current.value?.name ?: "Подключение…", null))
        wanted = true
        if (running) return
        Vpn.setStatus(Status.Connecting, "Загружаю серверы…")
        connecting = scope.launch {
            lock.withLock {
                if (!wanted) return@withLock
                Vpn.setStatus(Status.Connecting, "Загружаю серверы…")
                try {
                    connect()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    Log.e(TAG, "connect", e)
                    Vpn.event("Ошибка: ${e.message}")
                    shutdown(Status.Failed, e.message ?: "Не удалось подключиться")
                    // No server got through: maybe white lists. The probe finds out without the VPN.
                    PhoneProbe.launch(this@SquadVpnService)
                }
            }
        }
    }

    private suspend fun connect() {
        val profile = Profile.current
        val nodes = Subscriptions.load(profile)
        Vpn.setNodes(nodes)
        failed.clear()
        netId = NetworkId.current(this)
        candidates = ordered(nodes)

        val node = pickNode(Prefs.selectedNode) ?: throw IllegalStateException("Ни один сервер не ответил. Обнови подписку или выбери другую")

        Vpn.setStatus(Status.Connecting, "Подключаюсь к ${node.name}…")
        val pfd = establish() ?: throw IllegalStateException("Нет разрешения на VPN")
        tun = pfd
        startCore(node)
        Prefs.wasConnected = true
        Vpn.setStatus(Status.Connected)
        Vpn.event("Подключено: ${node.name} (${profile.title})")
        monitor = scope.launch { watch() }
        watchNetwork()
        // Fill the node list with pings in the background, then let the
        // phone probe look at the white lists (when the user turned it on).
        scope.launch {
            // The app's own way out in white-list mode (updates, the probe): say if it is shut.
            Http.socksProblem()?.let { Vpn.event("Внутренний прокси не отвечает: $it") }
            pingRest(nodes)
            PhoneProbe.maybeRun(this@SquadVpnService)
        }
    }

    /**
     * The node that worked last time (unless it stopped answering), then
     * known-alive nodes by ping, then the subscription's own order (it is
     * ranked), and the ones that did not answer last.
     */
    private fun ordered(nodes: List<Node>): List<Node> {
        val pings = Vpn.pings.value
        val alive = nodes.filter { (pings[it.key] ?: 0) > 0 }.sortedBy { pings[it.key] }
        val unknown = nodes.filter { it.key !in pings }
        val dead = nodes.filter { pings[it.key] == Pinger.DEAD }
        val byPing = alive + unknown + dead
        val good = Prefs.lastGoodOn(netId)
        val last = byPing.firstOrNull { it.key == good && pings[it.key] != Pinger.DEAD }
            ?: return byPing
        return listOf(last) + (byPing - last)
    }

    /**
     * The node to use: the hand-picked one, or the fastest of the first
     * candidates that answer. Batches of 8 so a dead head of the list does
     * not keep the user waiting.
     */
    private suspend fun pickNode(selectedKey: String?): Node? {
        candidates.firstOrNull { it.key == selectedKey }?.let { node ->
            Vpn.setStatus(Status.Connecting, "Проверяю ${node.name}…")
            val ms = Pinger.ping(node)
            Vpn.setPing(node.key, ms)
            if (ms > 0) return node
            failed += node.key
            Vpn.event("Выбранный сервер ${node.name} не отвечает, ищу другой")
        }
        val pool = candidates.filter { it.key !in failed }
        for (batch in pool.chunked(8).take(5)) {
            Vpn.setStatus(Status.Connecting, "Ищу лучший сервер…")
            val results = kotlinx.coroutines.coroutineScope {
                batch.map { node -> async { node to Pinger.ping(node).also { Vpn.setPing(node.key, it) } } }
                    .map { it.await() }
            }
            // The last good node wins its batch while it answers reasonably fast: no needless hop.
            val good = Prefs.lastGoodOn(netId)
            val best = results.firstOrNull { it.first.key == good && it.second in 1..LAST_GOOD_MAX_MS }
                ?: results.filter { it.second > 0 }.minByOrNull { it.second }
            if (best != null) return best.first
            results.forEach { failed += it.first.key }
        }
        return null
    }

    private fun establish(): ParcelFileDescriptor? {
        if (prepare(this) != null) return null
        val builder = Builder()
            .setSession("SQUAD VPN")
            .setMtu(XrayConfig.MTU)
            .addAddress("10.10.14.1", 30)
            .addRoute("0.0.0.0", 0)
            .addAddress("fd66:5155:5155::1", 126)
            .addRoute("::", 0)
            .addDnsServer(XrayConfig.TUN_DNS)
            .setConfigureIntent(
                PendingIntent.getActivity(
                    this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
                ),
            )
        // The app (and the Xray core inside it) stays outside the tunnel.
        builder.addDisallowedApplication(packageName)
        // Banks, Госуслуги and the like go straight to the internet. An app
        // that was removed from the phone is skipped.
        for (pkg in DirectApps.selected) runCatching { builder.addDisallowedApplication(pkg) }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) builder.setMetered(false)
        return builder.establish()
    }

    private fun startCore(node: Node) {
        val fd = tun?.fd ?: throw IllegalStateException("VPN-интерфейс закрыт")
        if (core.isRunning) core.stopLoop()
        val ruDirect = Prefs.ruDirect && Profile.current != Profile.WHITELIST
        core.startLoop(XrayConfig.vpn(node, ruDirect), fd)
        if (!core.isRunning) throw IllegalStateException("Ядро Xray не запустилось")
        Vpn.setCurrent(node)
        Prefs.setLastGoodOn(netId, node.key)
        Vpn.setPingNow(Vpn.pings.value[node.key]?.takeIf { it > 0 })
        updateNotification()
    }

    private suspend fun watch() {
        var misses = 0
        var tick = 0
        var last = System.nanoTime()
        while (scope.isActive) {
            delay(2_000)
            val now = System.nanoTime()
            val seconds = (now - last) / 1e9
            last = now
            // The stats manager disappears while the core restarts: skip a beat then.
            if (lock.tryLock()) {
                try {
                    if (core.isRunning) readTraffic(seconds)
                } finally {
                    lock.unlock()
                }
            }
            if (++tick % 2 == 0) updateNotification()
            // Every 30 min; PhoneProbe itself reports at most once an hour.
            if (tick % 900 == 0) scope.launch { PhoneProbe.maybeRun(this@SquadVpnService) }
            if (tick % 8 != 0) continue
            val ms = lock.withLock { measure() }
            if (ms > 0) {
                misses = 0
                Vpn.setPingNow(ms)
                Vpn.current.value?.let { Vpn.setPing(it.key, ms) }
            } else if (++misses >= 2) {
                misses = 0
                failover("сервер перестал отвечать")
            }
        }
    }

    /**
     * Wi-Fi <-> mobile: connections of the old network are dead, so the core
     * restarts on the same VPN interface (as v2rayNG does), and Android learns
     * which network the VPN runs over.
     */
    private fun watchNetwork() {
        val cm = getSystemService(ConnectivityManager::class.java)
        var lastNetwork: Network? = cm.activeNetwork
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                setUnderlyingNetworks(arrayOf(network))
                if (network == lastNetwork) return
                val first = lastNetwork == null
                lastNetwork = network
                if (first) return
                scope.launch {
                    lock.withLock {
                        // Nodes that failed on the old network get another chance.
                        failed.clear()
                        netId = NetworkId.current(this@SquadVpnService)
                        val node = Vpn.current.value ?: return@withLock
                        if (Vpn.status.value != Status.Connected) return@withLock
                        runCatching { startCore(node) }
                            .onSuccess { Vpn.event("Сеть сменилась, переподключился") }
                            .onFailure { shutdown(Status.Failed, it.message ?: "Ядро не перезапустилось") }
                    }
                }
            }
        }
        runCatching { cm.registerDefaultNetworkCallback(callback) }
        networkCallback = callback
    }

    private fun unwatchNetwork() {
        networkCallback?.let { cb ->
            runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(cb) }
        }
        networkCallback = null
    }

    private fun measure(): Long =
        try {
            if (core.isRunning) core.measureDelay(XrayConfig.TEST_URL) else Pinger.DEAD
        } catch (e: Exception) {
            Pinger.DEAD
        }

    /** "tag,uplink,123;tag,downlink,456;" — counters reset on every read. */
    private fun readTraffic(seconds: Double) {
        val stats = runCatching { core.queryAllOutboundTrafficStats() }.getOrNull().orEmpty()
        var down = 0L
        var up = 0L
        for (entry in stats.split(';')) {
            val parts = entry.split(',')
            if (parts.size != 3 || parts[0] == "dns-out") continue
            val value = parts[2].toLongOrNull() ?: continue
            if (parts[1] == "downlink") down += value else up += value
        }
        Vpn.addTraffic(down, up, seconds)
    }

    private suspend fun failover(reason: String): Unit = lock.withLock {
        if (!wanted || Vpn.status.value != Status.Connected) return@withLock
        val current = Vpn.current.value
        current?.let {
            failed += it.key
            Vpn.setPing(it.key, Pinger.DEAD)
        }
        Vpn.event("Меняю сервер: $reason")
        candidates = ordered(Vpn.nodes.value)
        val next = pickNode(null)
        // Disconnect pressed during the search: no new node.
        if (!wanted) return@withLock
        if (next == null) {
            Vpn.event("Других живых серверов нет, остаюсь на текущем")
            failed.clear()
            Vpn.setStatus(Status.Connected)
            return@withLock
        }
        runCatching { startCore(next) }
            .onSuccess {
                Vpn.setStatus(Status.Connected)
                Vpn.event("Новый сервер: ${next.name}")
            }
            .onFailure { shutdown(Status.Failed, it.message ?: "Ядро не перезапустилось") }
        Unit
    }

    /** The list of apps without VPN changed: a new VPN interface, same node. */
    private suspend fun reloadApps(): Unit = lock.withLock {
        if (Vpn.status.value != Status.Connected) return@withLock
        val node = Vpn.current.value ?: return@withLock
        val old = tun
        // The new interface replaces the old one right away; the core moves over to it.
        val pfd = try {
            establish() ?: return@withLock
        } catch (e: Exception) {
            shutdown(Status.Failed, e.message ?: "Не удалось пересоздать VPN")
            return@withLock
        }
        tun = pfd
        runCatching { startCore(node) }
            .onSuccess { Vpn.event("Список приложений без VPN обновлён") }
            .onFailure { shutdown(Status.Failed, it.message ?: "Ядро не перезапустилось") }
        old?.close()
        Unit
    }

    private suspend fun switchTo(key: String?, reason: String): Unit = lock.withLock {
        if (!wanted || Vpn.status.value != Status.Connected) return@withLock
        val nodes = Vpn.nodes.value
        candidates = ordered(nodes)
        failed.clear()
        val picked = if (key == null) {
            Vpn.setStatus(Status.Connecting, "Ищу лучший сервер…")
            pickNode(null)
        } else {
            nodes.firstOrNull { it.key == key }
        }
        if (!wanted) return@withLock
        val node = picked ?: run {
            Vpn.setStatus(Status.Connected)
            return@withLock
        }
        runCatching { startCore(node) }
            .onSuccess {
                Vpn.setStatus(Status.Connected)
                Vpn.event("Сервер ${node.name}: $reason")
            }
            .onFailure { shutdown(Status.Failed, it.message ?: "Ядро не перезапустилось") }
        Unit
    }

    /** The same check as the Servers screen button, so Stop there stops it too. */
    private suspend fun pingRest(nodes: List<Node>) {
        val stale = nodes.filter { !Vpn.isFresh(it.key) }
        if (stale.isEmpty() || Vpn.isPinging) return
        Pinger.startCheck(stale).join()
    }

    private fun stop(message: String) {
        wanted = false
        Prefs.wasConnected = false
        Vpn.setStatus(Status.Disconnecting)
        // A connection, switch or failover still searching for a node is dropped right away.
        connecting?.cancel()
        switching?.cancel()
        monitor?.cancel()
        scope.launch {
            lock.withLock { shutdown(Status.Disconnected, null) }
            Vpn.event(message)
        }
    }

    private fun shutdown(status: Status, message: String?) {
        monitor?.cancel()
        monitor = null
        unwatchNetwork()
        runCatching { if (core.isRunning) core.stopLoop() }
        tun?.close()
        tun = null
        Vpn.setStatus(status, message)
        if (status == Status.Failed) wanted = false
        // A start that came in while this stop was finishing keeps the service.
        // Checked again on the main thread, where onStartCommand runs: a start
        // between this check and stopSelf() would otherwise be killed.
        if (wanted) return
        ContextCompat.getMainExecutor(this).execute {
            if (!wanted) {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    private fun foreground(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun updateNotification() {
        val node = Vpn.current.value ?: return
        val traffic = Vpn.traffic.value
        val text = "↓ ${formatSpeed(traffic.downBps)}   ↑ ${formatSpeed(traffic.upBps)}"
        getSystemService(android.app.NotificationManager::class.java)
            .notify(NOTIFICATION_ID, notification(node.name, text))
    }

    private fun notification(title: String, text: String?): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, SquadVpnService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, App.CHANNEL_VPN)
            .setSmallIcon(R.drawable.ic_shield)
            .setColor(0xFFD00018.toInt())
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setContentIntent(open)
            .addAction(0, "Отключить", stop)
            .also { StatusBar.promote(it, "VPN") }
            .build()
    }

    companion object {
        private const val TAG = "SquadVpn"
        private const val NOTIFICATION_ID = 1
        private const val LAST_GOOD_MAX_MS = 1_500L
        const val ACTION_START = "com.squad.vpn.START"
        const val ACTION_STOP = "com.squad.vpn.STOP"
        const val ACTION_SWITCH = "com.squad.vpn.SWITCH"
        const val ACTION_FAILOVER = "com.squad.vpn.FAILOVER"
        const val ACTION_RELOAD_APPS = "com.squad.vpn.RELOAD_APPS"

        /** False when Android refused to start the service from the background. */
        fun send(context: Context, action: String): Boolean {
            val intent = Intent(context, SquadVpnService::class.java).setAction(action)
            return try {
                if (action == ACTION_START) {
                    ContextCompat.startForegroundService(context, intent)
                } else {
                    context.startService(intent)
                }
                true
            } catch (e: Exception) {
                Log.w(TAG, "send $action", e)
                false
            }
        }
    }
}
