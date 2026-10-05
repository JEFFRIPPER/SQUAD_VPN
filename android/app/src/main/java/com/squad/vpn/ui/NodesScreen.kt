package com.squad.vpn.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Sort
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.squad.vpn.core.Node
import com.squad.vpn.core.Pinger
import com.squad.vpn.core.Profile
import com.squad.vpn.core.Vpn

@Composable
fun NodesScreen(
    profile: Profile,
    selected: String?,
    onSelect: (String?) -> Unit,
    onPingAll: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val nodes by Vpn.nodes.collectAsStateWithLifecycle()
    val pings by Vpn.pings.collectAsStateWithLifecycle()
    val pinging by Vpn.pinging.collectAsStateWithLifecycle()
    val current by Vpn.current.collectAsStateWithLifecycle()
    var byPing by rememberSaveable { mutableStateOf(true) }

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
    val alive = pings.count { (k, v) -> v > 0 && nodes.any { it.key == k } }

    LazyColumn(
        modifier,
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(key = "header") {
            Column(Modifier.padding(bottom = 8.dp)) {
                Text(profile.title, style = MaterialTheme.typography.headlineMedium)
                Text(
                    if (nodes.isEmpty()) "Узлы появятся после первой загрузки подписки"
                    else "${nodes.size} узлов · отвечают $alive",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Row(
                    Modifier.padding(top = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    FilledTonalButton(onClick = onPingAll, enabled = !pinging && nodes.isNotEmpty()) {
                        if (pinging) {
                            CircularProgressIndicator(Modifier.size(ButtonDefaults.IconSize), strokeWidth = 2.dp)
                        } else {
                            Icon(Icons.Rounded.Speed, null, Modifier.size(ButtonDefaults.IconSize))
                        }
                        Spacer(Modifier.width(8.dp))
                        Text(if (pinging) "Проверяю…" else "Проверить пинг")
                    }
                    FilterChip(
                        selected = byPing,
                        onClick = { byPing = !byPing },
                        label = { Text("По пингу") },
                        leadingIcon = { Icon(Icons.Rounded.Sort, null, Modifier.size(18.dp)) },
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
    val container by animateColorAsState(
        if (selected) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surfaceContainerLow,
        Motion.gentle(),
        label = "container",
    )
    val lift by animateFloatAsState(if (selected) 1.02f else 1f, Motion.bouncy(), label = "lift")
    Card(
        modifier
            .fillMaxWidth()
            .graphicsLayer {
                scaleX = lift
                scaleY = lift
            }
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = container),
        shape = MaterialTheme.shapes.large,
    ) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            RadioButton(selected = selected, onClick = onClick)
            if (icon) {
                Icon(Icons.Rounded.AutoAwesome, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(end = 8.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    if (active) "сейчас используется" else subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
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
        ping == null -> "—" to MaterialTheme.colorScheme.onSurfaceVariant
        ping <= 0 -> "нет ответа" to MaterialTheme.colorScheme.error
        ping < 400 -> "$ping мс" to Sq.good
        ping < 1000 -> "$ping мс" to Sq.warn
        else -> "$ping мс" to MaterialTheme.colorScheme.error
    }
    val animated by animateColorAsState(color, label = "ping")
    Text(text, color = animated, style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(start = 8.dp))
}
