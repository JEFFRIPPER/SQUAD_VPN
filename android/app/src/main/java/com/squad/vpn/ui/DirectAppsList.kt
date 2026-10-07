package com.squad.vpn.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.squad.vpn.core.DirectApps
import com.squad.vpn.core.Prefs
import com.squad.vpn.ui.glass.GlassChip
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassRadius
import com.squad.vpn.ui.glass.GlassSpacing
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Apps that bypass the VPN: installed apps with a tick each, ticked first. */
@Composable
fun DirectAppsList(onChange: () -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val iconPx = with(LocalDensity.current) { 36.dp.roundToPx() }
    var only by remember { mutableStateOf(Prefs.onlyApps) }
    var apps by remember { mutableStateOf<List<DirectApps.App>?>(null) }
    var ticked by remember(only) { mutableStateOf(DirectApps.ticked(only)) }
    var query by remember { mutableStateOf("") }
    // Ticked apps first: reload the order when the mode changes.
    LaunchedEffect(only) {
        apps = withContext(Dispatchers.IO) { DirectApps.installed(context, iconPx, DirectApps.ticked(only)) }
    }

    Column(modifier) {
        Row(horizontalArrangement = Arrangement.spacedBy(GlassSpacing.xs)) {
            GlassChip(
                text = "Мимо VPN",
                selected = !only,
                onClick = {
                    if (only) {
                        only = false
                        Prefs.onlyApps = false
                        onChange()
                    }
                },
            )
            GlassChip(
                text = "Только эти через VPN",
                selected = only,
                onClick = {
                    if (!only) {
                        only = true
                        Prefs.onlyApps = true
                        onChange()
                    }
                },
            )
        }
        Text(
            if (only) {
                "Через VPN идут только отмеченные приложения, остальные напрямую. Пока ничего не отмечено, через VPN идёт всё"
            } else {
                "Отмеченные приложения ходят в интернет напрямую, мимо VPN. Банки и Госуслуги отмечены заранее"
            },
            style = MaterialTheme.typography.bodySmall,
            color = GlassColors.onGlassVariant,
            modifier = Modifier.padding(top = GlassSpacing.xs),
        )
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("Поиск") },
            singleLine = true,
            shape = RoundedCornerShape(GlassRadius.md),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = GlassColors.focusRing,
                unfocusedBorderColor = GlassColors.onGlassVariant.copy(alpha = 0.4f),
                focusedLabelColor = GlassColors.focusRing,
                cursorColor = GlassColors.focusRing,
            ),
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = GlassSpacing.xs),
        )
        val list = apps
        if (list == null) {
            LinearProgressIndicator(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = GlassSpacing.sm),
                color = GlassColors.red,
                trackColor = GlassColors.onGlass.copy(alpha = 0.12f),
            )
            return@Column
        }
        val shown = remember(list, query) {
            val q = query.trim()
            if (q.isEmpty()) list else list.filter { it.label.contains(q, ignoreCase = true) || it.pkg.contains(q, ignoreCase = true) }
        }
        LazyColumn(Modifier.heightIn(max = 420.dp)) {
            items(shown, key = { it.pkg }) { app ->
                val checked = app.pkg in ticked
                val toggle = {
                    ticked = if (checked) ticked - app.pkg else ticked + app.pkg
                    DirectApps.setTicked(only, ticked)
                    onChange()
                }
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clickable(onClick = toggle)
                        .padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    val icon = app.icon
                    if (icon != null) {
                        Image(remember(icon) { icon.asImageBitmap() }, null, Modifier.size(36.dp))
                    } else {
                        Spacer(Modifier.size(36.dp))
                    }
                    Text(
                        app.label,
                        style = MaterialTheme.typography.bodyLarge,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier
                            .weight(1f)
                            .padding(horizontal = GlassSpacing.sm),
                    )
                    Checkbox(
                        checked = checked,
                        onCheckedChange = { toggle() },
                        colors = CheckboxDefaults.colors(
                            checkedColor = GlassColors.red,
                            uncheckedColor = GlassColors.onGlassVariant,
                            checkmarkColor = GlassColors.onAccent,
                        ),
                    )
                }
            }
        }
    }
}
