package com.squad.vpn.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.SystemUpdate
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.squad.vpn.core.Updater
import com.squad.vpn.ui.glass.GlassButton
import com.squad.vpn.ui.glass.GlassButtonStyle
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassEasing
import com.squad.vpn.ui.glass.GlassLevel
import com.squad.vpn.ui.glass.GlassRadius
import com.squad.vpn.ui.glass.GlassSpacing
import com.squad.vpn.ui.glass.GlassSurface

/** Height the pages make room for while the banner is shown. */
val UpdateBannerHeight = 88.dp

/**
 * "A new version is out": a glass panel with a softly glowing brand tint and
 * a big ОБНОВИТЬ button, shown on every screen until the update is installed.
 */
@Composable
fun UpdateBanner(state: Updater.State, onUpdate: () -> Unit, modifier: Modifier = Modifier) {
    val glow by rememberInfiniteTransition(label = "glow").animateFloat(
        initialValue = 0.55f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(1400, easing = GlassEasing.standard), RepeatMode.Reverse),
        label = "glowValue",
    )
    val version = when (state) {
        is Updater.State.Available -> state.info.versionName
        is Updater.State.Downloading -> state.info.versionName
        is Updater.State.Ready -> state.info.versionName
        is Updater.State.Error -> state.info?.versionName.orEmpty()
        else -> ""
    }
    GlassSurface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(GlassRadius.xl),
        level = GlassLevel.Raised,
        accent = glow,
    ) {
        Row(
            Modifier.padding(horizontal = GlassSpacing.md, vertical = GlassSpacing.sm),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Rounded.SystemUpdate, null, tint = GlassColors.onGlass, modifier = Modifier.size(28.dp))
            Spacer(Modifier.width(GlassSpacing.sm))
            Column(Modifier.weight(1f)) {
                Text(
                    "Доступно обновление",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
                Text(
                    when (state) {
                        is Updater.State.Downloading -> "Скачиваю ${(state.progress * 100).toInt()}%"
                        is Updater.State.Ready -> "Скачано, осталось установить"
                        is Updater.State.Error -> "Не скачалось, попробуй ещё раз"
                        else -> "Версия $version"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = GlassColors.onGlassVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (state is Updater.State.Downloading) {
                    LinearProgressIndicator(
                        progress = { state.progress },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = GlassSpacing.xxs)
                            .height(3.dp),
                        color = GlassColors.red,
                        trackColor = GlassColors.onGlass.copy(alpha = 0.12f),
                    )
                }
            }
            Spacer(Modifier.width(GlassSpacing.sm))
            GlassButton(
                text = if (state is Updater.State.Ready) "УСТАНОВИТЬ" else "ОБНОВИТЬ",
                onClick = onUpdate,
                style = GlassButtonStyle.Filled,
                loading = state is Updater.State.Downloading,
            )
        }
    }
}
