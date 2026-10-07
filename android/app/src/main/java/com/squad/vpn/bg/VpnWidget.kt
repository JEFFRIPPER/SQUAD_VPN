package com.squad.vpn.bg

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import com.squad.vpn.R
import com.squad.vpn.core.Status
import com.squad.vpn.core.Vpn

/** Home screen widget: the shield turns the VPN on and off, the line shows the server. */
class VpnWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        render(context, manager, ids)
    }

    companion object {
        /** Called on every status or server change (App watches [Vpn]). */
        fun updateAll(context: Context) {
            val manager = AppWidgetManager.getInstance(context) ?: return
            val ids = runCatching { manager.getAppWidgetIds(ComponentName(context, VpnWidget::class.java)) }.getOrNull()
            if (ids == null || ids.isEmpty()) return
            render(context, manager, ids)
        }

        private fun render(context: Context, manager: AppWidgetManager, ids: IntArray) {
            val status = Vpn.status.value
            val on = status == Status.Connected
            val text = when (status) {
                Status.Connected -> Vpn.current.value?.name ?: "Подключено"
                Status.Connecting -> "Подключение…"
                Status.Disconnecting -> "Отключение…"
                Status.Failed -> "Ошибка, нажми ещё раз"
                Status.Disconnected -> "Отключено"
            }
            // A tap is a user action, so the service may start in the foreground from here.
            val toggle = PendingIntent.getForegroundService(
                context,
                5,
                Intent(context, SquadVpnService::class.java).setAction(SquadVpnService.ACTION_TOGGLE),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            val views = RemoteViews(context.packageName, R.layout.widget_vpn).apply {
                setTextViewText(R.id.widget_status, text)
                setInt(R.id.widget_icon, "setBackgroundResource", if (on) R.drawable.widget_icon_on else R.drawable.widget_icon_off)
                setOnClickPendingIntent(R.id.widget_root, toggle)
            }
            runCatching { manager.updateAppWidget(ids, views) }
        }
    }
}
