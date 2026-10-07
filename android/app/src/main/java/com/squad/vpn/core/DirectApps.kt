package com.squad.vpn.core

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import androidx.core.graphics.drawable.toBitmap

/**
 * Apps that bypass the VPN (split tunneling by app): banks, Госуслуги and
 * marketplaces often refuse foreign addresses, so by default they go
 * straight to the internet. The user can change the list in Settings.
 */
object DirectApps {
    /**
     * Ticked until the user changes the list. Only installed apps matter: a
     * package that is not on the phone is skipped.
     */
    val PRESET: Set<String> = setOf(
        "ru.sberbankmobile", // СберБанк Онлайн
        "com.idamob.tinkoff.android", // Т-Банк
        "ru.vtb24.mobilebanking.android", // ВТБ Онлайн
        "ru.alfabank.mobile.android", // Альфа-Банк
        "ru.raiffeisennews", // Райффайзен Банк
        "ru.rostel", // Госуслуги
        "ru.nspk.mirpay", // Mir Pay
        "ru.yoo.money", // ЮMoney
        "ru.ozon.app.android", // Ozon
        "com.wildberries.ru", // Wildberries
    )

    class App(val pkg: String, val label: String, val icon: Bitmap?)

    /** The packages that bypass the VPN now. */
    val selected: Set<String> get() = Prefs.directApps ?: PRESET

    /** "Только эти через VPN" is on and has apps: Android then sends only them into the tunnel. */
    val onlyMode: Boolean get() = Prefs.onlyApps && Prefs.vpnApps.isNotEmpty()

    /** The ticked list of the mode shown: through the VPN, or around it. */
    fun ticked(only: Boolean): Set<String> = if (only) Prefs.vpnApps else selected

    fun setTicked(only: Boolean, packages: Set<String>) {
        if (only) Prefs.vpnApps = packages else Prefs.directApps = packages
    }

    /**
     * Apps with a launcher icon, ticked ones first, then by name. Slow (icons):
     * call off the main thread. The manifest's <queries> makes them visible.
     */
    fun installed(context: Context, iconPx: Int, ticked: Set<String> = selected): List<App> {
        val pm = context.packageManager
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(launcher, 0)
            .map { it.activityInfo.applicationInfo }
            .distinctBy { it.packageName }
            .filter { it.packageName != context.packageName }
            .map { info ->
                App(
                    pkg = info.packageName,
                    label = info.loadLabel(pm).toString(),
                    icon = runCatching { info.loadIcon(pm).toBitmap(iconPx, iconPx) }.getOrNull(),
                )
            }
            .sortedWith(compareBy<App> { it.pkg !in ticked }.thenBy { it.label.lowercase() })
    }
}
