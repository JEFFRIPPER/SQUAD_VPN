package com.squad.vpn.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.squad.vpn.ui.glass.GlassButton
import com.squad.vpn.ui.glass.GlassButtonStyle
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassSpacing

/** First start: what the app does and what Android has to allow. */
@Composable
fun Onboarding(onAskVpn: () -> Unit, onDone: () -> Unit) {
    Column(
        Modifier
            .heightIn(max = 560.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            "SQUAD VPN сам берёт свежие бесплатные серверы, выбирает самый быстрый и переходит на другой, " +
                "если сервер отвалился. Выбери подписку на главном экране и нажми на большую кнопку.",
            style = MaterialTheme.typography.bodyMedium,
            color = GlassColors.onGlassVariant,
        )
        Text(
            "Что нужно разрешить",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(top = GlassSpacing.md, bottom = GlassSpacing.xxs),
        )
        PermissionsList(onAskVpn = onAskVpn)
        Text(
            "Всё это можно проверить позже в «Настройках».",
            style = MaterialTheme.typography.bodySmall,
            color = GlassColors.onGlassVariant,
            modifier = Modifier.padding(top = GlassSpacing.xs),
        )
        GlassButton(
            text = "Готово",
            onClick = onDone,
            icon = Icons.Rounded.Check,
            style = GlassButtonStyle.Filled,
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = GlassSpacing.md),
        )
    }
}
