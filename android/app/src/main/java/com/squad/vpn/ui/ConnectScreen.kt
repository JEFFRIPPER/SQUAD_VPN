package com.squad.vpn.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.ArrowDownward
import androidx.compose.material.icons.rounded.ArrowUpward
import androidx.compose.material.icons.rounded.LockOpen
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.squad.vpn.bg.SquadVpnService
import com.squad.vpn.core.Node
import com.squad.vpn.core.Profile
import com.squad.vpn.core.SpeedState
import com.squad.vpn.core.SpeedTest
import com.squad.vpn.core.Status
import com.squad.vpn.core.Vpn
import com.squad.vpn.ui.glass.GlassButton
import com.squad.vpn.ui.glass.GlassCard
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassDuration
import com.squad.vpn.ui.glass.GlassScale
import com.squad.vpn.ui.glass.GlassSegmented
import com.squad.vpn.ui.glass.GlassSpacing
import com.squad.vpn.ui.glass.GlassSpring
import com.squad.vpn.ui.glass.LocalBackdrop
import kotlinx.coroutines.delay

@Composable
fun ConnectScreen(
    profile: Profile,
    selected: String?,
    onProfile: (Profile) -> Unit,
    onPower: () -> Unit,
    onFailover: () -> Unit,
    onOpenServers: () -> Unit,
    onOpenEvents: () -> Unit,
    contentPadding: PaddingValues,
    modifier: Modifier = Modifier,
) {
    val status by Vpn.status.collectAsStateWithLifecycle()
    val message by Vpn.message.collectAsStateWithLifecycle()
    val node by Vpn.current.collectAsStateWithLifecycle()
    val ping by Vpn.ping.collectAsStateWithLifecycle()
    val traffic by Vpn.traffic.collectAsStateWithLifecycle()
    val since by Vpn.since.collectAsStateWithLifecycle()
    val events by Vpn.events.collectAsStateWithLifecycle()
    val blocked by Vpn.blocked.collectAsStateWithLifecycle()
    val autoWhitelist by Vpn.autoWhitelist.collectAsStateWithLifecycle()
    val context = LocalContext.current

    val scroll = rememberScrollState()
    val backdrop = LocalBackdrop.current
    LaunchedEffect(scroll) { snapshotFlow { scroll.value.toFloat() }.collect { backdrop.scroll = it } }

    Column(
        modifier
            .verticalScroll(scroll)
            .padding(contentPadding)
            .padding(horizontal = GlassSpacing.md),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        PowerButton(status = status, onClick = onPower)

        AnimatedContent(
            targetState = status,
            transitionSpec = {
                (slideInVertically(GlassSpring.bouncy()) { it / 2 } + fadeIn(tween(GlassDuration.medium)))
                    .togetherWith(slideOutVertically(GlassSpring.spatial()) { -it / 2 } + fadeOut(tween(GlassDuration.short)))
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
                modifier = Modifier.padding(top = GlassSpacing.xxs),
            )
        }
        val sub = when (status) {
            Status.Connected -> if (autoWhitelist) "Оператор включил белые списки: подписка «Белые списки»" else "Подписка «${profile.title}»"
            Status.Connecting, Status.Failed -> message ?: ""
            else -> "Нажми, чтобы пустить трафик телефона через лучшие серверы"
        }
        AnimatedContent(
            targetState = sub,
            transitionSpec = { fadeIn(tween(GlassDuration.medium)) togetherWith fadeOut(tween(GlassDuration.short)) },
            label = "sub",
        ) {
            Text(
                it,
                style = MaterialTheme.typography.bodyMedium,
                color = GlassColors.onGlassVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = GlassSpacing.xs, start = GlassSpacing.lg, end = GlassSpacing.lg),
            )
        }

        Spacer(Modifier.height(GlassSpacing.lg))
        ServerCard(status, node, selected, onOpenServers, onFailover)

        Spacer(Modifier.height(GlassSpacing.md))
        val choices = listOf(Profile.TOP, Profile.BEST, Profile.WHITELIST)
        GlassSegmented(
            options = choices.map { it.title },
            selected = choices.indexOf(profile),
            onSelect = { onProfile(choices[it]) },
        )
        AnimatedContent(
            targetState = profile,
            transitionSpec = { fadeIn(tween(GlassDuration.medium)) togetherWith fadeOut(tween(GlassDuration.short)) },
            label = "hint",
        ) {
            Text(
                if (it == Profile.CUSTOM) "Своя подписка из настроек" else it.hint,
                style = MaterialTheme.typography.bodySmall,
                color = GlassColors.onGlassVariant,
                modifier = Modifier.padding(top = GlassSpacing.xs),
            )
        }

        QuickToggles(Modifier.padding(top = GlassSpacing.sm))
        // Kill switch holds the internet closed: the power button reconnects, this one gives up.
        AnimatedVisibility(
            visible = blocked && status == Status.Failed,
            enter = fadeIn(tween(GlassDuration.medium)) + scaleIn(GlassSpring.bouncy(), initialScale = GlassScale.enter),
            exit = fadeOut(tween(GlassDuration.short)) + scaleOut(tween(GlassDuration.short), targetScale = GlassScale.enter),
        ) {
            GlassButton(
                text = "Открыть интернет без VPN",
                onClick = { SquadVpnService.send(context, SquadVpnService.ACTION_STOP) },
                icon = Icons.Rounded.LockOpen,
                modifier = Modifier.padding(top = GlassSpacing.sm),
            )
        }

        Spacer(Modifier.height(GlassSpacing.md))
        Row(horizontalArrangement = Arrangement.spacedBy(GlassSpacing.sm)) {
            StatCard("Пинг сейчас", Modifier.weight(1f), index = 1) {
                Text(ping?.let { "$it мс" } ?: "—", style = numberStyle)
                Text("проверка каждые 16 с", style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant)
            }
            StatCard("Эта сессия", Modifier.weight(1f), index = 2) {
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
                    color = GlassColors.onGlassVariant,
                )
            }
        }
        Spacer(Modifier.height(GlassSpacing.sm))
        StatCard("Скорость", Modifier.fillMaxWidth(), index = 3) {
            Row(horizontalArrangement = Arrangement.spacedBy(GlassSpacing.lg), verticalAlignment = Alignment.CenterVertically) {
                Speed(Icons.Rounded.ArrowDownward, formatSpeed(traffic.downBps))
                Speed(Icons.Rounded.ArrowUpward, formatSpeed(traffic.upBps))
            }
            Sparkline(
                traffic.history,
                Modifier
                    .fillMaxWidth()
                    .height(40.dp)
                    .padding(top = GlassSpacing.xs),
            )
            SpeedTestRow(connected = status == Status.Connected)
        }
        Spacer(Modifier.height(GlassSpacing.sm))
        StatCard("События", Modifier.fillMaxWidth(), index = 4, onClick = if (events.isEmpty()) null else onOpenEvents) {
            if (events.isEmpty()) {
                Text("пока пусто", color = GlassColors.onGlassVariant)
            } else {
                events.take(4).forEach {
                    Text(it, style = MaterialTheme.typography.bodySmall, maxLines = 1, modifier = Modifier.padding(vertical = 2.dp))
                }
                Row(Modifier.padding(top = GlassSpacing.xs), verticalAlignment = Alignment.CenterVertically) {
                    Text("Все события", style = MaterialTheme.typography.labelLarge, color = GlassColors.focusRing)
                    Icon(
                        Icons.AutoMirrored.Rounded.KeyboardArrowRight,
                        null,
                        tint = GlassColors.focusRing,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
        }
        Spacer(Modifier.height(GlassSpacing.lg))
    }
}

/**
 * The server in use, or the one the next connection starts with. A tap
 * opens the list; while connected the button moves to another server.
 */
@Composable
private fun ServerCard(status: Status, current: Node?, selected: String?, onOpen: () -> Unit, onSwitch: () -> Unit) {
    val nodes by Vpn.nodes.collectAsStateWithLifecycle()
    val pings by Vpn.pings.collectAsStateWithLifecycle()
    val node = current ?: selected?.let { key -> nodes.firstOrNull { it.key == key } }
    val connected = status == Status.Connected
    StatCard(if (connected) "Сервер" else "Следующий сервер", Modifier.fillMaxWidth(), index = 0, onClick = onOpen) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                AnimatedContent(
                    targetState = node?.name ?: "Самый быстрый",
                    transitionSpec = { fadeIn(tween(GlassDuration.medium)) togetherWith fadeOut(tween(GlassDuration.short)) },
                    label = "server",
                ) {
                    Text(it, style = MaterialTheme.typography.titleLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                val note = if (node == null) {
                    val alive = nodes.count { (pings[it.key] ?: 0L) > 0 }
                    if (nodes.isEmpty()) "список серверов загружается" else "выберется сам: отвечают $alive из ${nodes.size}"
                } else {
                    val ping = pings[node.key]
                    val pingText = when {
                        ping == null -> "пинг не проверен"
                        ping > 0 -> "$ping мс"
                        else -> "не отвечает"
                    }
                    "${node.protocol.uppercase()} · $pingText"
                }
                Text(note, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant, maxLines = 1)
            }
            if (connected) {
                Spacer(Modifier.width(GlassSpacing.xs))
                GlassButton(text = "Сменить", onClick = onSwitch, icon = Icons.Rounded.SwapHoriz)
            } else {
                Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, null, tint = GlassColors.onGlassVariant)
            }
        }
    }
}

/** The test button and its result under the live speed. */
@Composable
private fun SpeedTestRow(connected: Boolean) {
    val test by SpeedTest.state.collectAsStateWithLifecycle()
    val running = test is SpeedState.Running
    Row(
        Modifier
            .fillMaxWidth()
            .padding(top = GlassSpacing.sm),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            val (value, note) = when (val t = test) {
                is SpeedState.Running -> formatMbps(t.mbps) to "замер…"
                is SpeedState.Done -> formatMbps(t.mbps) to t.server
                is SpeedState.Error -> "—" to t.message
                SpeedState.Idle -> "—" to "до ${SpeedTest.MAX_BYTES / 1_000_000} МБ трафика"
            }
            AnimatedContent(
                targetState = value,
                transitionSpec = { fadeIn(tween(GlassDuration.short)) togetherWith fadeOut(tween(GlassDuration.short)) },
                label = "mbps",
            ) { Text(it, style = MaterialTheme.typography.titleLarge) }
            Text(note, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant, maxLines = 1)
        }
        GlassButton(
            text = if (running) "Стоп" else "Тест скорости",
            onClick = { if (running) SpeedTest.stop() else SpeedTest.start() },
            icon = if (running) Icons.Rounded.Stop else Icons.Rounded.Speed,
            enabled = connected || running,
        )
    }
}

private fun formatMbps(mbps: Double): String =
    if (mbps < 10) String.format(java.util.Locale.ROOT, "%.1f Мбит/с", mbps) else "${mbps.toInt()} Мбит/с"

@Composable
private fun Speed(icon: androidx.compose.ui.graphics.vector.ImageVector, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = GlassColors.focusRing, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(GlassSpacing.xxs))
        Text(text, style = MaterialTheme.typography.titleLarge)
    }
}

/**
 * A glass card with a label that rises into place on a spring when first
 * shown, staggered by [index] (fade + translate + soft scale).
 */
@Composable
fun StatCard(
    label: String,
    modifier: Modifier = Modifier,
    index: Int = 0,
    onClick: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    var shown by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        delay(60L * index)
        shown = true
    }
    val progress by animateFloatAsState(if (shown) 1f else 0f, GlassSpring.bouncy(), label = "card")
    GlassCard(
        modifier = modifier.graphicsLayer {
            alpha = progress.coerceIn(0f, 1f)
            translationY = (1f - progress) * 48.dp.toPx()
            val s = GlassScale.enter + (1f - GlassScale.enter) * progress
            scaleX = s
            scaleY = s
        },
        onClick = onClick,
    ) {
        Text(label.uppercase(), style = MaterialTheme.typography.labelMedium, color = GlassColors.onGlassVariant)
        Spacer(Modifier.height(GlassSpacing.xs))
        content()
    }
}

@Composable
private fun Sparkline(values: List<Long>, modifier: Modifier = Modifier) {
    val color = GlassColors.focusRing
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
