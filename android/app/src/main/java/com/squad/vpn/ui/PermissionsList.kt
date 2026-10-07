package com.squad.vpn.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.HelpOutline
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import com.squad.vpn.core.Permissions
import com.squad.vpn.ui.glass.GlassButton
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassDuration
import com.squad.vpn.ui.glass.GlassSpacing
import com.squad.vpn.ui.glass.GlassSpring

/**
 * What the VPN needs from Android: a green tick when done, else a button
 * that opens the right page. Checked again each time the app comes back.
 */
@Composable
fun PermissionsList(onAskVpn: () -> Unit) {
    val context = LocalContext.current
    var round by remember { mutableIntStateOf(0) }
    LifecycleResumeEffect(Unit) {
        round++
        onPauseOrDispose { }
    }
    val vpn = remember(round) { Permissions.vpn(context) }
    val notifications = remember(round) { Permissions.notifications(context) }
    val battery = remember(round) { Permissions.battery(context) }

    Column {
        Need("VPN", "Разрешение Android на создание VPN-подключения", vpn, onFix = onAskVpn)
        Need(
            "Уведомления",
            "Без них Android может закрыть VPN, а ты не увидишь, что он отключился",
            notifications,
            onFix = { Permissions.openNotificationSettings(context) },
        )
        Need(
            "Работа в фоне",
            "Сними ограничение батареи, чтобы VPN не засыпал при выключенном экране",
            battery,
            onFix = { Permissions.askBattery(context) },
        )
        if (Permissions.isXiaomi) {
            Need(
                "Автозапуск (Xiaomi)",
                "Включи для SQUAD VPN, чтобы он поднимался после перезагрузки. Android не сообщает, включён ли он",
                ok = null,
                onFix = { Permissions.openAutostart(context) },
            )
        }
    }
}

/** [ok] null: Android does not tell, the user checks it there. */
@Composable
private fun Need(title: String, text: String, ok: Boolean?, onFix: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = GlassSpacing.xs),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        AnimatedContent(
            targetState = ok,
            transitionSpec = { (scaleIn(GlassSpring.bouncy()) + fadeIn(tween(GlassDuration.medium))) togetherWith fadeOut(tween(GlassDuration.short)) },
            label = "need",
        ) { done ->
            val (icon, tint) = when (done) {
                true -> Icons.Rounded.CheckCircle to GlassColors.good
                false -> Icons.Rounded.ErrorOutline to GlassColors.warn
                null -> Icons.AutoMirrored.Rounded.HelpOutline to GlassColors.onGlassVariant
            }
            Icon(icon, null, tint = tint, modifier = Modifier.size(24.dp))
        }
        Spacer(Modifier.width(GlassSpacing.sm))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(text, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant)
        }
        if (ok != true) {
            Spacer(Modifier.width(GlassSpacing.xs))
            GlassButton(text = if (ok == null) "Открыть" else "Включить", onClick = onFix)
        }
    }
}
