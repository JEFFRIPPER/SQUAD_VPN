package com.squad.vpn

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import com.squad.vpn.bg.UpdateJob
import com.squad.vpn.bg.VpnWidget
import com.squad.vpn.core.Vpn
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import com.squad.vpn.core.PingStore
import com.squad.vpn.core.Prefs
import com.squad.vpn.core.TrafficStore
import libv2ray.Libv2ray

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        instance = this
        Prefs.init(this)
        PingStore.init(this)
        TrafficStore.init(this)
        // Xray reads geo files from here (none are used) and keeps its xudp key.
        Libv2ray.initCoreEnv(filesDir.absolutePath, Prefs.deviceKey)
        val notifications = getSystemService(NotificationManager::class.java)
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL_VPN, "VPN", NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false)
            },
        )
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL_UPDATES, "Обновления", NotificationManager.IMPORTANCE_DEFAULT),
        )
        UpdateJob.schedule(this)
        // The home screen widget follows the VPN: status and server.
        CoroutineScope(SupervisorJob() + Dispatchers.Main).launch {
            combine(Vpn.status, Vpn.current) { status, node -> status to node?.name }
                .distinctUntilChanged()
                .collect { VpnWidget.updateAll(this@App) }
        }
    }

    companion object {
        const val CHANNEL_VPN = "vpn"
        const val CHANNEL_UPDATES = "updates"
        lateinit var instance: App
            private set
        val context: Context get() = instance
    }
}
