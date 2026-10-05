package com.squad.vpn.bg

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService
import com.squad.vpn.core.Prefs

/** Brings the VPN back after a reboot or an app update, if it was on and the user asked for it. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        Prefs.init(context)
        if (!Prefs.autoConnect || !Prefs.wasConnected) return
        if (VpnService.prepare(context) != null) return
        SquadVpnService.send(context, SquadVpnService.ACTION_START)
    }
}
