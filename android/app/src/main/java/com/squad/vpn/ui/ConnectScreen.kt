package com.squad.vpn.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowDownward
import androidx.compose.material.icons.rounded.ArrowUpward
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import com.squad.vpn.R
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.squad.vpn.core.Profile
import com.squad.vpn.core.Status
import com.squad.vpn.core.Vpn
import kotlinx.coroutines.delay

@Composable
fun ConnectScreen(
    profile: Profile,
    onProfile: (Profile) -> Unit,
    onPower: () -> Unit,
    onFailover: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val status by Vpn.status.collectAsStateWithLifecycle()
    val message by Vpn.message.collectAsStateWithLifecycle()
    val node by Vpn.current.collectAsStateWithLifecycle()
    val ping by Vpn.ping.collectAsStateWithLifecycle()
    val traffic by Vpn.traffic.collectAsStateWithLifecycle()
    val since by Vpn.since.collectAsStateWithLifecycle()
    val events by Vpn.events.collectAsStateWithLifecycle()

    Column(
        modifier
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(
            Modifier.padding(top = 12.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Image(
                painterResource(R.drawable.squad_logo),
                contentDescription = "Логотип SQUAD",
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape),
            )
            Spacer(Modifier.width(10.dp))
            Text("SQUAD VPN", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        }
        PowerButton(status = status, onClick = onPower)

        AnimatedContent(
            targetState = status,
            transitionSpec = {
                (slideInVertically(Motion.bouncy()) { it / 2 } + fadeIn(tween(220)))
                    .togetherWith(slideOutVertically(Motion.gentle()) { -it / 2 } + fadeOut(tween(150)))
            },
            label = "state",
        ) { s ->
            Text(
                when (s) {
                    Status.Disconnected -> "Не подключено"
                    Status.Connecting -> "Подключение…"
                    Status.Connected -> "Подключено"
                    Status.Disconnecting -> "Отключение…"
                    Status.Failed -> "Не удалось подключиться"
                },
                style = MaterialTheme.typography.headlineMedium,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        val sub = when (status) {
            Status.Connected -> node?.name ?: ""
            Status.Connecting, Status.Failed -> message ?: ""
            else -> "Нажми, чтобы пустить трафик телефона через лучшие узлы"
        }
        AnimatedContent(targetState = sub, transitionSpec = { fadeIn(tween(250)) togetherWith fadeOut(tween(150)) }, label = "sub") {
            Text(
                it,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 6.dp, start = 24.dp, end = 24.dp),
            )
        }

        Spacer(Modifier.height(20.dp))
        val choices = listOf(Profile.TOP, Profile.BEST, Profile.WHITELIST)
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            choices.forEachIndexed { index, p ->
                SegmentedButton(
                    selected = profile == p,
                    onClick = { onProfile(p) },
                    shape = SegmentedButtonDefaults.itemShape(index, choices.size),
                ) {
                    Text(p.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
        AnimatedContent(targetState = profile, label = "hint") {
            Text(
                if (it == Profile.CUSTOM) "Своя подписка из настроек" else it.hint,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 6.dp),
            )
        }

        AnimatedVisibility(
            visible = status == Status.Connected,
            enter = fadeIn() + scaleIn(Motion.bouncy(), initialScale = 0.8f),
            exit = fadeOut(),
        ) {
            FilledTonalButton(onClick = onFailover, modifier = Modifier.padding(top = 12.dp)) {
                Icon(Icons.Rounded.SwapHoriz, null, Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.width(8.dp))
                Text("Сменить узел")
            }
        }

        Spacer(Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StatCard("Пинг сейчас", Modifier.weight(1f), index = 0) {
                Text(ping?.let { "$it мс" } ?: "—", style = numberStyle)
                Text("проверка каждые 16 с", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            StatCard("Эта сессия", Modifier.weight(1f), index = 1) {
                var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
                LaunchedEffect(since) {
                    while (since > 0) {
                        now = System.currentTimeMillis()
                        delay(1000)
                    }
                }
                Text(if (since > 0) formatDuration(now - since) else "—", style = numberStyle)
                Text(
                    "↓ ${formatBytes(traffic.downTotal)}  ↑ ${formatBytes(traffic.upTotal)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(Modifier.height(12.dp))
        StatCard("Скорость", Modifier.fillMaxWidth(), index = 2) {
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp), verticalAlignment = Alignment.CenterVertically) {
                Speed(Icons.Rounded.ArrowDownward, formatSpeed(traffic.downBps))
                Speed(Icons.Rounded.ArrowUpward, formatSpeed(traffic.upBps))
            }
            Sparkline(traffic.history, Modifier.fillMaxWidth().height(40.dp).padding(top = 8.dp))
        }
        Spacer(Modifier.height(12.dp))
        StatCard("События", Modifier.fillMaxWidth(), index = 3) {
            if (events.isEmpty()) {
                Text("пока пусто", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                events.take(8).forEach {
                    Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(vertical = 2.dp))
                }
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun Speed(icon: androidx.compose.ui.graphics.vector.ImageVector, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(4.dp))
        Text(text, style = MaterialTheme.typography.titleLarge)
    }
}

/** A card that springs into place, staggered by [index]. */
@Composable
fun StatCard(label: String, modifier: Modifier = Modifier, index: Int = 0, content: @Composable () -> Unit) {
    var shown by remember { androidx.compose.runtime.mutableStateOf(false) }
    LaunchedEffect(Unit) {
        delay(60L * index)
        shown = true
    }
    val progress by animateFloatAsState(if (shown) 1f else 0f, Motion.bouncy(), label = "card")
    Card(
        modifier.graphicsLayer {
            alpha = progress.coerceIn(0f, 1f)
            translationY = (1f - progress) * 48.dp.toPx()
            val s = 0.92f + 0.08f * progress
            scaleX = s
            scaleY = s
        },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
        shape = MaterialTheme.shapes.large,
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(label.uppercase(), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(6.dp))
            content()
        }
    }
}

@Composable
private fun Sparkline(values: List<Long>, modifier: Modifier = Modifier) {
    val color = MaterialTheme.colorScheme.primary
    Canvas(modifier) {
        if (values.size < 2) return@Canvas
        val max = (values.maxOrNull() ?: 1L).coerceAtLeast(1L).toFloat()
        val step = size.width / (values.size - 1)
        val path = Path()
        values.forEachIndexed { i, v ->
            val p = Offset(i * step, size.height - v / max * size.height)
            if (i == 0) path.moveTo(p.x, p.y) else path.lineTo(p.x, p.y)
        }
        drawPath(path, color, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round))
    }
}
