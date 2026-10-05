package com.squad.vpn

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import com.squad.vpn.core.Prefs
import libv2ray.Libv2ray

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        instance = this
        Prefs.init(this)
        // Xray reads geo files from here (none are used) and keeps its xudp key.
        Libv2ray.initCoreEnv(filesDir.absolutePath, Prefs.deviceKey)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL_VPN, "VPN", NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false)
            },
        )
    }

    companion object {
        const val CHANNEL_VPN = "vpn"
        lateinit var instance: App
            private set
        val context: Context get() = instance
    }
}
