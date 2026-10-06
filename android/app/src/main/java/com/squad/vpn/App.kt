package com.squad.vpn

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import com.squad.vpn.bg.UpdateJob
import com.squad.vpn.core.PingStore
import com.squad.vpn.core.Prefs
import libv2ray.Libv2ray

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        instance = this
        Prefs.init(this)
        PingStore.init(this)
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
    }

    companion object {
        const val CHANNEL_VPN = "vpn"
        const val CHANNEL_UPDATES = "updates"
        lateinit var instance: App
            private set
        val context: Context get() = instance
    }
}
