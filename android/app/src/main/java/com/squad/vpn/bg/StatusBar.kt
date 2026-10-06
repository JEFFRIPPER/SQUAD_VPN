package com.squad.vpn.bg

import android.app.Notification
import android.app.NotificationManager
import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.core.app.NotificationCompat
import com.squad.vpn.R

/**
 * The app in the phone's status bar and quick settings: the "SQUAD VPN"
 * tile in the notification shade, and the VPN notification as an Android 16
 * Live Update, which the system shows as a chip in the status bar.
 *
 * Android 16 APIs are reached by name: the app is compiled against
 * Android 15, and on older phones these calls simply do nothing.
 */
object StatusBar {
    private const val ANDROID_16 = 36

    /**
     * Asks Android to put the SQUAD VPN tile into quick settings (Android 13+:
     * a system dialog). [done] gets a line for the user.
     */
    fun requestTile(context: Context, done: (String) -> Unit) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            done(MANUAL)
            return
        }
        val manager = context.getSystemService(StatusBarManager::class.java)
        if (manager == null) {
            done(MANUAL)
            return
        }
        try {
            manager.requestAddTileService(
                ComponentName(context, QuickTile::class.java),
                context.getString(R.string.app_name),
                Icon.createWithResource(context, R.drawable.ic_shield),
                context.mainExecutor,
            ) { result ->
                done(
                    when (result) {
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ADDED -> "Кнопка добавлена в шторку"
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ALREADY_ADDED -> "Кнопка уже есть в шторке"
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_NOT_ADDED -> "Кнопку не добавили"
                        else -> MANUAL
                    },
                )
            }
        } catch (e: Exception) {
            done(MANUAL)
        }
    }

    private const val MANUAL =
        "Телефон не дал добавить кнопку сам. Опусти шторку, нажми карандаш (изменить) и перетащи плитку SQUAD VPN наверх"

    /** Live Updates allowed for the app: null before Android 16, where there are none. */
    fun liveUpdatesAllowed(context: Context): Boolean? {
        if (Build.VERSION.SDK_INT < ANDROID_16) return null
        val manager = context.getSystemService(NotificationManager::class.java)
        return runCatching {
            NotificationManager::class.java.getMethod("canPostPromotedNotifications").invoke(manager) as Boolean
        }.getOrNull()
    }

    /** The system page where the user allows Live Updates for this app. */
    fun openLiveUpdateSettings(context: Context) {
        val action = constant(Settings::class.java, "ACTION_MANAGE_APP_PROMOTED_NOTIFICATIONS")
        val intent = if (action != null) {
            Intent(action).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
        } else {
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { context.startActivity(intent) }.onFailure {
            context.startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        }
    }

    /**
     * Ask Android 16 to promote the ongoing VPN notification to a Live Update:
     * a chip with the shield and [chip] in the status bar. The notification
     * must stay ongoing, titled, not colorized and without custom views.
     */
    fun promote(builder: NotificationCompat.Builder, chip: String) {
        if (Build.VERSION.SDK_INT < ANDROID_16) return
        val request = constant(Notification::class.java, "EXTRA_REQUEST_PROMOTED_ONGOING") ?: return
        val extras = Bundle().apply { putBoolean(request, true) }
        constant(Notification::class.java, "EXTRA_SHORT_CRITICAL_TEXT")?.let { extras.putString(it, chip) }
        builder.addExtras(extras)
    }

    private fun constant(owner: Class<*>, name: String): String? =
        runCatching { owner.getField(name).get(null) as? String }.getOrNull()
}
