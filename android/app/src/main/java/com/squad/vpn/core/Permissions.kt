package com.squad.vpn.core

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.net.VpnService
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat

/** What the VPN needs from Android and where the user turns it on. */
object Permissions {
    fun vpn(context: Context): Boolean = VpnService.prepare(context) == null

    /** Covers the Android 13+ permission too: without it this is false. */
    fun notifications(context: Context): Boolean = NotificationManagerCompat.from(context).areNotificationsEnabled()

    /** Without it Android may put the VPN to sleep when the screen is off. */
    fun battery(context: Context): Boolean =
        context.getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(context.packageName) ?: true

    /** Xiaomi, Redmi and POCO also have their own autostart switch; Android does not tell its state. */
    val isXiaomi: Boolean =
        listOf(Build.MANUFACTURER, Build.BRAND).any { it.equals("Xiaomi", true) || it.equals("Redmi", true) || it.equals("POCO", true) }

    fun allGranted(context: Context): Boolean = vpn(context) && notifications(context) && battery(context)

    fun openNotificationSettings(context: Context) {
        open(
            context,
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName),
            appDetails(context),
        )
    }

    fun askBattery(context: Context) {
        open(
            context,
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${context.packageName}")),
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
        )
    }

    fun openAutostart(context: Context) {
        open(
            context,
            Intent().setComponent(ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity")),
            appDetails(context),
        )
    }

    private fun appDetails(context: Context) =
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))

    /** The first page that opens on this phone. */
    private fun open(context: Context, vararg intents: Intent) {
        for (intent in intents) {
            if (runCatching { context.startActivity(intent) }.isSuccess) return
        }
    }
}
