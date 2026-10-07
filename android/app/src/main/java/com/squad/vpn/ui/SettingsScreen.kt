package com.squad.vpn.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.SystemUpdate
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.squad.vpn.BuildConfig
import com.squad.vpn.bg.SquadVpnService
import com.squad.vpn.bg.StatusBar
import com.squad.vpn.core.PhoneProbe
import com.squad.vpn.core.Prefs
import com.squad.vpn.core.Profile
import com.squad.vpn.core.Subscriptions
import com.squad.vpn.core.Updater
import com.squad.vpn.core.Vpn
import com.squad.vpn.ui.glass.GlassButton
import com.squad.vpn.ui.glass.GlassButtonStyle
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassRadius
import com.squad.vpn.ui.glass.GlassSpacing
import com.squad.vpn.ui.glass.LocalBackdrop
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import libv2ray.Libv2ray

@Composable
fun SettingsScreen(
    profile: Profile,
    onProfile: (Profile) -> Unit,
    refreshing: Boolean,
    refreshNote: String?,
    onRefresh: () -> Unit,
    onOpenApps: () -> Unit,
    contentPadding: PaddingValues,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val update by Updater.state.collectAsStateWithLifecycle()
    var customUrl by remember { mutableStateOf(Prefs.customUrl) }
    var pasteNote by remember { mutableStateOf<String?>(null) }
    val clipboard = LocalClipboardManager.current
    var ruDirect by remember { mutableStateOf(Prefs.ruDirect) }
    var autoConnect by remember { mutableStateOf(Prefs.autoConnect) }
    var antiDpi by remember { mutableStateOf(Prefs.antiDpi) }
    var probeEnabled by remember { mutableStateOf(Prefs.probeEnabled) }
    var tileNote by remember { mutableStateOf<String?>(null) }
    var liveAllowed by remember { mutableStateOf(StatusBar.liveUpdatesAllowed(context)) }
    // Back from Android's settings page: show what the user chose there.
    LifecycleResumeEffect(Unit) {
        liveAllowed = StatusBar.liveUpdatesAllowed(context)
        onPauseOrDispose { }
    }
    var probeToken by remember { mutableStateOf(Prefs.probeToken) }
    val probeRunning by PhoneProbe.running.collectAsStateWithLifecycle()
    val probeNote by PhoneProbe.note.collectAsStateWithLifecycle()
    val coreVersion = remember { runCatching { Libv2ray.checkVersionX() }.getOrDefault("") }
    val scroll = rememberScrollState()
    val backdrop = LocalBackdrop.current
    LaunchedEffect(scroll) { snapshotFlow { scroll.value.toFloat() }.collect { backdrop.scroll = it } }
    val radio = RadioButtonDefaults.colors(selectedColor = GlassColors.focusRing, unselectedColor = GlassColors.onGlassVariant)

    Column(
        modifier
            .verticalScroll(scroll)
            .padding(contentPadding)
            .padding(horizontal = GlassSpacing.md),
        verticalArrangement = Arrangement.spacedBy(GlassSpacing.sm),
    ) {
        Text("Настройки", style = MaterialTheme.typography.headlineMedium)

        StatCard("Подписка", Modifier.fillMaxWidth(), index = 0) {
            Profile.entries.forEach { p ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clickable { onProfile(p) }
                        .padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    RadioButton(selected = profile == p, onClick = { onProfile(p) }, colors = radio)
                    Column(Modifier.weight(1f)) {
                        Text(p.title, style = MaterialTheme.typography.titleMedium)
                        Text(p.hint, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant)
                    }
                }
            }
            AnimatedVisibility(
                visible = profile == Profile.CUSTOM,
                enter = expandVertically(Motion.gentle()) + fadeIn(),
                exit = shrinkVertically(Motion.gentle()) + fadeOut(),
            ) {
                OutlinedTextField(
                    value = customUrl,
                    onValueChange = {
                        customUrl = it
                        Prefs.customUrl = it
                    },
                    label = { Text("Ссылка на подписку или ключи") },
                    maxLines = 4,
                    shape = RoundedCornerShape(GlassRadius.md),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = GlassColors.focusRing,
                        unfocusedBorderColor = GlassColors.onGlassVariant.copy(alpha = 0.4f),
                        focusedLabelColor = GlassColors.focusRing,
                        cursorColor = GlassColors.focusRing,
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp),
                )
            }
            // A link copied from a channel or a friend: one tap, no typing.
            GlassButton(
                text = "Вставить из буфера",
                onClick = {
                    val text = clipboard.getText()?.text?.trim().orEmpty()
                    if (!text.contains("://")) {
                        pasteNote = "В буфере нет ссылки: скопируй подписку или ключ vless://…"
                    } else {
                        pasteNote = null
                        customUrl = text
                        Prefs.customUrl = text
                        // The old copy goes: switching to "Своя ссылка" then loads the new one.
                        Subscriptions.forget(Profile.CUSTOM)
                        if (profile == Profile.CUSTOM) onRefresh() else onProfile(Profile.CUSTOM)
                    }
                },
                icon = Icons.Rounded.ContentPaste,
                modifier = Modifier.padding(top = 8.dp),
            )
            pasteNote?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant, modifier = Modifier.padding(top = 4.dp))
            }
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                GlassButton(
                    text = "Обновить",
                    onClick = onRefresh,
                    icon = Icons.Rounded.Refresh,
                    loading = refreshing,
                )
                Spacer(Modifier.width(12.dp))
                Text(
                    refreshNote ?: formatAgo(Subscriptions.updatedAt(profile)),
                    style = MaterialTheme.typography.bodySmall,
                    color = GlassColors.onGlassVariant,
                )
            }
        }

        StatCard("Подключение", Modifier.fillMaxWidth(), index = 1) {
            SwitchRow(
                "Российские сайты напрямую",
                "Сайты .ru, .su и .рф видят твой обычный адрес. В «Белых списках» всё идёт через VPN",
                ruDirect,
            ) {
                ruDirect = it
                Prefs.ruDirect = it
            }
            SwitchRow(
                "Обход DPI",
                "Дробит начало защищённого соединения с сервером на мелкие части, чтобы оператор не узнал сервер. " +
                    "Включи, если серверы не подключаются или быстро отваливаются",
                antiDpi,
            ) {
                antiDpi = it
                Prefs.antiDpi = it
                // Servers that looked dead may answer now (or the other way round).
                Vpn.forgetDead()
                // A running VPN picks it up at once: same server, new connection.
                if (Vpn.isConnected) SquadVpnService.send(context, SquadVpnService.ACTION_RELOAD_APPS)
            }
            Row(
                Modifier
                    .fillMaxWidth()
                    .clickable(onClick = onOpenApps)
                    .padding(vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Приложения и VPN", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Какие приложения идут мимо VPN, или только какие идут через него",
                        style = MaterialTheme.typography.bodySmall,
                        color = GlassColors.onGlassVariant,
                    )
                }
                Icon(Icons.Rounded.ChevronRight, null, tint = GlassColors.onGlassVariant)
            }
            NavRow("Кнопка в шторке", tileNote ?: "SQUAD VPN в быстрых настройках, рядом с Wi-Fi и Bluetooth") {
                StatusBar.requestTile(context) { tileNote = it }
            }
            liveAllowed?.let { allowed ->
                NavRow(
                    "Значок в строке состояния",
                    if (allowed) {
                        "Включён: пока VPN подключён, наверху экрана горит щит SQUAD VPN"
                    } else {
                        "Выключен в настройках Android. Нажми и разреши обновления в реальном времени"
                    },
                ) { StatusBar.openLiveUpdateSettings(context) }
            }
            SwitchRow(
                "Подключаться автоматически",
                "При запуске приложения и после перезагрузки телефона",
                autoConnect,
            ) {
                autoConnect = it
                Prefs.autoConnect = it
            }
        }

        TrafficCard(index = 2)

        StatCard("Проверка белых списков", Modifier.fillMaxWidth(), index = 2) {
            Text(
                "Когда мобильный интернет урезают до белых списков, телефон проверяет серверы «Белых списков» " +
                    "и отправляет результат на GitHub. Подписка ставит ответившие у тебя серверы первыми. " +
                    "В отчёте только результаты проверки, без номера, IP и оператора.",
                style = MaterialTheme.typography.bodySmall,
                color = GlassColors.onGlassVariant,
            )
            SwitchRow(
                "Проверять белые списки",
                "Не чаще раза в час, только на мобильном интернете с включённым VPN",
                probeEnabled,
            ) {
                probeEnabled = it
                Prefs.probeEnabled = it
            }
            OutlinedTextField(
                value = probeToken,
                onValueChange = {
                    probeToken = it
                    Prefs.probeToken = it
                },
                label = { Text("Токен GitHub") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                shape = RoundedCornerShape(GlassRadius.md),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = GlassColors.focusRing,
                    unfocusedBorderColor = GlassColors.onGlassVariant.copy(alpha = 0.4f),
                    focusedLabelColor = GlassColors.focusRing,
                    cursorColor = GlassColors.focusRing,
                ),
                modifier = Modifier.fillMaxWidth(),
            )
            Row(
                Modifier
                    .padding(top = GlassSpacing.sm)
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(GlassSpacing.xs),
            ) {
                GlassButton(
                    text = "Создать токен",
                    onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(PROBE_TOKEN_URL))) },
                )
                GlassButton(
                    text = "Проверить сейчас",
                    onClick = { scope.launch(Dispatchers.IO) { PhoneProbe.maybeRun(context.applicationContext, force = true) } },
                    loading = probeRunning,
                    enabled = probeEnabled && probeToken.isNotBlank(),
                )
            }
            if (probeNote.isNotEmpty()) {
                Text(
                    probeNote,
                    style = MaterialTheme.typography.bodySmall,
                    color = GlassColors.onGlassVariant,
                    modifier = Modifier.padding(top = GlassSpacing.xs),
                )
            }
        }

        StatCard("Обновления", Modifier.fillMaxWidth(), index = 3) {
            Text("Версия ${BuildConfig.VERSION_NAME} (сборка ${BuildConfig.VERSION_CODE})", style = MaterialTheme.typography.titleMedium)
            if (coreVersion.isNotEmpty()) {
                Text(coreVersion, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant)
            }
            Spacer(Modifier.height(8.dp))
            AnimatedContent(targetState = update, transitionSpec = { fadeIn() togetherWith fadeOut() }, label = "update") { s ->
                Column {
                    when (s) {
                        is Updater.State.Available -> {
                            Text("Доступна версия ${s.info.versionName}")
                            GlassButton(
                                text = "Скачать и установить",
                                onClick = { scope.launch { Updater.download(s.info) } },
                                icon = Icons.Rounded.SystemUpdate,
                                style = GlassButtonStyle.Filled,
                                modifier = Modifier.padding(top = GlassSpacing.xs),
                            )
                        }
                        is Updater.State.Downloading -> {
                            Text("Скачиваю ${s.info.versionName}…")
                            LinearProgressIndicator(
                                progress = { s.progress },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(top = GlassSpacing.xs),
                                color = GlassColors.red,
                                trackColor = GlassColors.onGlass.copy(alpha = 0.12f),
                            )
                        }
                        is Updater.State.Ready -> {
                            Text("Версия ${s.info.versionName} скачана")
                            GlassButton(
                                text = "Установить",
                                onClick = { Updater.install(context, s.file) },
                                style = GlassButtonStyle.Filled,
                                modifier = Modifier.padding(top = GlassSpacing.xs),
                            )
                        }
                        else -> {
                            val note = when (s) {
                                Updater.State.Checking -> "Проверяю…"
                                Updater.State.UpToDate -> "У тебя последняя версия"
                                is Updater.State.Error -> s.message
                                else -> "Новая версия ищется при каждом запуске и раз в 4 часа в фоне"
                            }
                            Text(note, color = GlassColors.onGlassVariant)
                            GlassButton(
                                text = "Проверить обновления",
                                onClick = { scope.launch { Updater.check() } },
                                loading = s == Updater.State.Checking,
                                modifier = Modifier.padding(top = GlassSpacing.xs),
                            )
                        }
                    }
                }
            }
        }

        StatCard("О приложении", Modifier.fillMaxWidth(), index = 4) {
            Text("SQUAD VPN для Android: те же подписки и серверы, что у программы для Windows.")
            GlassButton(
                text = "Открыть GitHub",
                onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/${BuildConfig.REPO}"))) },
                modifier = Modifier.padding(top = GlassSpacing.sm),
            )
        }
        Spacer(Modifier.height(16.dp))
    }
}

@Composable
private fun NavRow(title: String, subtitle: String, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant)
        }
        Icon(Icons.Rounded.ChevronRight, null, tint = GlassColors.onGlassVariant)
    }
}

@Composable
private fun SwitchRow(title: String, subtitle: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable { onChange(!checked) }
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = GlassColors.onGlassVariant)
        }
        Spacer(Modifier.width(12.dp))
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(
                checkedTrackColor = GlassColors.red,
                checkedThumbColor = GlassColors.onAccent,
                uncheckedTrackColor = GlassColors.onGlass.copy(alpha = 0.08f),
                uncheckedBorderColor = GlassColors.onGlassVariant.copy(alpha = 0.6f),
                uncheckedThumbColor = GlassColors.onGlassVariant,
            ),
        )
    }
}

/** A classic token that can only write to public repositories, this one included. */
private const val PROBE_TOKEN_URL =
    "https://github.com/settings/tokens/new?scopes=public_repo&description=SQUAD%20VPN%20phone%20probe"
