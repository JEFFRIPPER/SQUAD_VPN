package com.squad.vpn.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.squad.vpn.core.TrafficStore
import com.squad.vpn.ui.glass.GlassColors
import java.text.SimpleDateFormat
import java.util.Locale

/** Settings card: traffic through the VPN today, this month and over the last week. */
@Composable
fun TrafficCard(index: Int, modifier: Modifier = Modifier) {
    val version by TrafficStore.version.collectAsStateWithLifecycle()
    val today = remember(version) { TrafficStore.today() }
    val month = remember(version) { TrafficStore.month() }
    val week = remember(version) { TrafficStore.lastDays(7) }

    StatCard("Трафик", modifier.fillMaxWidth(), index = index) {
        Line("Сегодня", "↓ ${formatBytes(today.down)}   ↑ ${formatBytes(today.up)}")
        Line("За месяц", formatBytes(month.total))
        val max = week.maxOf { it.total }.coerceAtLeast(1)
        val bar = GlassColors.red
        val track = GlassColors.onGlass.copy(alpha = 0.10f)
        Canvas(
            Modifier
                .fillMaxWidth()
                .height(72.dp)
                .padding(top = 12.dp),
        ) {
            val slot = size.width / week.size
            val width = slot * 0.56f
            val radius = CornerRadius(width / 2, width / 2)
            week.forEachIndexed { i, day ->
                val x = slot * i + (slot - width) / 2
                drawRoundRect(track, Offset(x, 0f), Size(width, size.height), radius)
                val h = size.height * day.total / max
                if (h > 0f) drawRoundRect(bar, Offset(x, size.height - h), Size(width, h), radius)
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            val parse = remember { SimpleDateFormat("yyyy-MM-dd", Locale.ROOT) }
            val weekday = remember { SimpleDateFormat("EE", Locale("ru")) }
            week.forEach { day ->
                Text(
                    runCatching { weekday.format(parse.parse(day.date)!!) }.getOrDefault(""),
                    style = MaterialTheme.typography.labelSmall,
                    color = GlassColors.onGlassVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.weight(1f),
                )
            }
        }
        Text(
            "Считается только на телефоне, без списка сайтов",
            style = MaterialTheme.typography.bodySmall,
            color = GlassColors.onGlassVariant,
            modifier = Modifier.padding(top = 8.dp),
        )
    }
}

@Composable
private fun Line(label: String, value: String) {
    Column(Modifier.padding(vertical = 2.dp)) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant)
        Text(value, style = MaterialTheme.typography.titleMedium)
    }
}
