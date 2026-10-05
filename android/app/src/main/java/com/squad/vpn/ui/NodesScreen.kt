package com.squad.vpn.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Sort
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.squad.vpn.core.Node
import com.squad.vpn.core.Pinger
import com.squad.vpn.core.Profile
import com.squad.vpn.core.Vpn
import com.squad.vpn.ui.glass.GlassButton
import com.squad.vpn.ui.glass.GlassCard
import com.squad.vpn.ui.glass.GlassChip
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassLevel
import com.squad.vpn.ui.glass.GlassRadius
import com.squad.vpn.ui.glass.GlassSpacing
import com.squad.vpn.ui.glass.LocalBackdrop

@Composable
fun NodesScreen(
    profile: Profile,
    selected: String?,
    onSelect: (String?) -> Unit,
    onPingAll: () -> Unit,
    contentPadding: PaddingValues,
    modifier: Modifier = Modifier,
) {
    val nodes by Vpn.nodes.collectAsStateWithLifecycle()
    val pings by Vpn.pings.collectAsStateWithLifecycle()
    val pinging by Vpn.pinging.collectAsStateWithLifecycle()
    val current by Vpn.current.collectAsStateWithLifecycle()
    var byPing by rememberSaveable { mutableStateOf(true) }

    val list = rememberLazyListState()
    val backdrop = LocalBackdrop.current
    LaunchedEffect(list) {
        // Rows are about 72 dp; an estimate is enough for parallax and the top bar.
        snapshotFlow { list.firstVisibleItemIndex * 200f + list.firstVisibleItemScrollOffset }
            .collect { backdrop.scroll = it }
    }

    val shown = remember(nodes, pings, byPing) {
        if (!byPing) {
            nodes
        } else {
            nodes.sortedWith(
                compareBy<Node> {
                    when (val p = pings[it.key]) {
                        null -> 1
                        Pinger.DEAD -> 2
                        else -> if (p > 0) 0 else 2
                    }
                }.thenBy { pings[it.key] ?: Long.MAX_VALUE },
            )
        }
    }
    val alive = remember(nodes, pings) {
        val keys = nodes.mapTo(HashSet()) { it.key }
        pings.count { (k, v) -> v > 0 && k in keys }
    }

    val direction = LocalLayoutDirection.current
    LazyColumn(
        modifier,
        state = list,
        contentPadding = PaddingValues(
            start = contentPadding.calculateStartPadding(direction) + GlassSpacing.md,
            end = contentPadding.calculateEndPadding(direction) + GlassSpacing.md,
            top = contentPadding.calculateTopPadding(),
            bottom = contentPadding.calculateBottomPadding() + GlassSpacing.md,
        ),
        verticalArrangement = Arrangement.spacedBy(GlassSpacing.xs),
    ) {
        item(key = "header") {
            Column(Modifier.padding(bottom = GlassSpacing.xs)) {
                Text(profile.title, style = MaterialTheme.typography.headlineMedium)
                Text(
                    if (nodes.isEmpty()) "Узлы появятся после первой загрузки подписки"
                    else "${nodes.size} узлов · отвечают $alive",
                    color = GlassColors.onGlassVariant,
                )
                Row(
                    Modifier.padding(top = GlassSpacing.sm),
                    horizontalArrangement = Arrangement.spacedBy(GlassSpacing.xs),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    GlassButton(
                        text = if (pinging) "Проверяю…" else "Проверить пинг",
                        onClick = onPingAll,
                        icon = Icons.Rounded.Speed,
                        enabled = nodes.isNotEmpty(),
                        loading = pinging,
                    )
                    GlassChip(
                        text = "По пингу",
                        selected = byPing,
                        onClick = { byPing = !byPing },
                        icon = Icons.Rounded.Sort,
                    )
                }
            }
        }
        item(key = "auto") {
            NodeRow(
                title = "Авто — лучший узел",
                subtitle = "Выбирает самый быстрый и сам меняет, если узел отвалится",
                ping = null,
                selected = selected == null,
                active = selected == null && current != null,
                icon = true,
                onClick = { onSelect(null) },
                modifier = Modifier.animateItem(),
            )
        }
        items(shown, key = { it.key }) { node ->
            NodeRow(
                title = node.name,
                subtitle = "${node.protocol} · ${node.server}",
                ping = pings[node.key],
                selected = selected == node.key,
                active = current?.key == node.key,
                icon = false,
                onClick = { onSelect(node.key) },
                modifier = Modifier.animateItem(),
            )
        }
    }
}

/** A list row: tonal (unblurred) glass, so the long list stays light and readable. */
@Composable
private fun NodeRow(
    title: String,
    subtitle: String,
    ping: Long?,
    selected: Boolean,
    active: Boolean,
    icon: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    GlassCard(
        modifier = modifier.fillMaxWidth(),
        onClick = onClick,
        selected = selected,
        radius = GlassRadius.lg,
        level = GlassLevel.Flat,
        contentPadding = PaddingValues(horizontal = GlassSpacing.sm, vertical = GlassSpacing.xs),
        role = Role.RadioButton,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            RadioButton(
                selected = selected,
                onClick = null,
                colors = RadioButtonDefaults.colors(selectedColor = GlassColors.focusRing, unselectedColor = GlassColors.onGlassVariant),
            )
            if (icon) {
                Icon(
                    Icons.Rounded.AutoAwesome,
                    null,
                    tint = GlassColors.focusRing,
                    modifier = Modifier.padding(start = GlassSpacing.xs, end = GlassSpacing.xs),
                )
            }
            Column(
                Modifier
                    .weight(1f)
                    .padding(start = GlassSpacing.xs),
            ) {
                Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    if (active) "сейчас используется" else subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (active) GlassColors.focusRing else GlassColors.onGlassVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (!icon) PingLabel(ping)
        }
    }
}

@Composable
private fun PingLabel(ping: Long?) {
    val (text, color) = when {
        ping == null -> "—" to GlassColors.onGlassVariant
        ping <= 0 -> "нет ответа" to GlassColors.bad
        ping < 400 -> "$ping мс" to GlassColors.good
        ping < 1000 -> "$ping мс" to GlassColors.warn
        else -> "$ping мс" to GlassColors.bad
    }
    val animated by animateColorAsState(color, label = "ping")
    Text(text, color = animated, style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(start = GlassSpacing.xs))
}
