package com.squad.vpn.bg

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.net.VpnService
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import com.squad.vpn.core.Status
import com.squad.vpn.core.Vpn
import com.squad.vpn.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/** Quick-settings tile: one tap to connect or disconnect. */
class QuickTile : TileService() {
    private var watcher: Job? = null

    override fun onStartListening() {
        watcher = CoroutineScope(Dispatchers.Main).launch {
            Vpn.status.collect { render(it) }
        }
    }

    override fun onStopListening() {
        watcher?.cancel()
        watcher = null
    }

    override fun onClick() {
        when (Vpn.status.value) {
            Status.Connected, Status.Connecting -> SquadVpnService.send(this, SquadVpnService.ACTION_STOP)
            else -> {
                // Without the VPN permission, or when Android does not let the
                // service start from here, the app's screen does the connecting.
                if (VpnService.prepare(this) != null || !SquadVpnService.send(this, SquadVpnService.ACTION_START)) {
                    openApp()
                }
            }
        }
    }

    private fun openApp() {
        val intent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra(MainActivity.EXTRA_CONNECT, true)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startActivityAndCollapse(
                PendingIntent.getActivity(this, TILE_REQUEST, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT),
            )
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }

    private fun render(status: Status) {
        val tile = qsTile ?: return
        tile.state = when (status) {
            Status.Connected -> Tile.STATE_ACTIVE
            Status.Connecting, Status.Disconnecting -> Tile.STATE_ACTIVE
            else -> Tile.STATE_INACTIVE
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            tile.updateTile()
            return
        }
        tile.subtitle = when (status) {
            Status.Connected -> Vpn.current.value?.name ?: "Подключено"
            Status.Connecting -> "Подключение…"
            Status.Disconnecting -> "Отключение…"
            Status.Failed -> "Ошибка"
            Status.Disconnected -> "Отключено"
        }
        tile.updateTile()
    }

    private companion object {
        /** Not 0: the VPN notification opens the app with request code 0 and no extras. */
        const val TILE_REQUEST = 4
    }
}
