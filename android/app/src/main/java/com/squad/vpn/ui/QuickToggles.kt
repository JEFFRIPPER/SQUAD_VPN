package com.squad.vpn.ui

import android.content.Context
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Block
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.squad.vpn.bg.SquadVpnService
import com.squad.vpn.core.Prefs
import com.squad.vpn.core.Vpn
import com.squad.vpn.ui.glass.GlassChip
import com.squad.vpn.ui.glass.GlassSpacing

/** Anti-DPI on or off, the same as the switch in the settings. */
fun applyAntiDpi(context: Context, on: Boolean) {
    Prefs.antiDpi = on
    // Servers that looked dead may answer now (or the other way round).
    Vpn.forgetDead()
    // A running VPN picks it up at once: same server, new connection.
    if (Vpn.isConnected) SquadVpnService.send(context, SquadVpnService.ACTION_RELOAD_APPS)
}

/** Main screen: the switches people reach for when a network acts up. Anti-DPI turns on by itself (Settings has the switch). */
@Composable
fun QuickToggles(modifier: Modifier = Modifier) {
    var killSwitch by remember { mutableStateOf(Prefs.killSwitch) }
    Row(
        modifier.horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(GlassSpacing.xs),
    ) {
        GlassChip(
            "Kill switch",
            selected = killSwitch,
            onClick = {
                killSwitch = !killSwitch
                Prefs.killSwitch = killSwitch
            },
            icon = Icons.Rounded.Block,
        )
    }
}
