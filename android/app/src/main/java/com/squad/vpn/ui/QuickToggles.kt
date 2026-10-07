package com.squad.vpn.ui

import android.content.Context
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.Security
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
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

/** Main screen: the switches people reach for when a network acts up. */
@Composable
fun QuickToggles(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    var antiDpi by remember { mutableStateOf(Prefs.antiDpi) }
    var killSwitch by remember { mutableStateOf(Prefs.killSwitch) }
    Row(
        modifier.horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(GlassSpacing.xs),
    ) {
        GlassChip(
            "Обход DPI",
            selected = antiDpi,
            onClick = {
                antiDpi = !antiDpi
                applyAntiDpi(context, antiDpi)
            },
            icon = Icons.Rounded.Security,
        )
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
