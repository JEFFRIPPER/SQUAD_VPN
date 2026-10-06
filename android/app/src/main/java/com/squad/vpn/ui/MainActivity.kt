package com.squad.vpn.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Dns
import androidx.compose.material.icons.rounded.PowerSettingsNew
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import com.squad.vpn.R
import com.squad.vpn.bg.SquadVpnService
import com.squad.vpn.bg.UpdateJob
import com.squad.vpn.core.Pinger
import com.squad.vpn.core.Prefs
import com.squad.vpn.core.Profile
import com.squad.vpn.core.Status
import com.squad.vpn.core.Subscriptions
import com.squad.vpn.core.Updater
import com.squad.vpn.core.Vpn
import com.squad.vpn.ui.glass.GlassBackground
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassDuration
import com.squad.vpn.ui.glass.GlassEasing
import com.squad.vpn.ui.glass.GlassNavBar
import com.squad.vpn.ui.glass.GlassNavItem
import com.squad.vpn.ui.glass.GlassSheet
import com.squad.vpn.ui.glass.GlassSize
import com.squad.vpn.ui.glass.GlassSnackbarHost
import com.squad.vpn.ui.glass.GlassSpacing
import com.squad.vpn.ui.glass.GlassSpring
import com.squad.vpn.ui.glass.GlassTopBar
import com.squad.vpn.ui.glass.LocalBackdrop
import com.squad.vpn.ui.glass.rememberBackdrop
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private val vpnPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (it.resultCode == RESULT_OK) SquadVpnService.send(this, SquadVpnService.ACTION_START)
        else Vpn.event("Без разрешения на VPN подключиться нельзя")
    }

    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // The app is always dark: light system bar icons on a transparent bar.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        lifecycleScope.launch(Dispatchers.IO) {
            if (Vpn.nodes.value.isEmpty()) Vpn.setNodes(Subscriptions.cached(Profile.current))
        }
        if (intent?.getBooleanExtra(UpdateJob.EXTRA_UPDATE, false) == true) updateRequested = true
        val wantsConnect = intent?.getBooleanExtra(EXTRA_CONNECT, false) == true
        if (savedInstanceState == null && (wantsConnect || Prefs.autoConnect) && Vpn.status.value == Status.Disconnected) {
            connect()
        }

        setContent {
            SquadTheme { App() }
        }
    }

    /** Set when the update notification opened the app: the download starts right away. */
    private var updateRequested by mutableStateOf(false)

    override fun onStart() {
        super.onStart()
        // Every time the app comes to the screen: is there a newer version?
        lifecycleScope.launch { Updater.checkIfDue() }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getBooleanExtra(UpdateJob.EXTRA_UPDATE, false)) updateRequested = true
        val status = Vpn.status.value
        if (intent.getBooleanExtra(EXTRA_CONNECT, false) && status != Status.Connected && status != Status.Connecting) connect()
    }

    fun connect() {
        val prepare = VpnService.prepare(this)
        if (prepare != null) vpnPermission.launch(prepare) else SquadVpnService.send(this, SquadVpnService.ACTION_START)
    }

    fun disconnect() = SquadVpnService.send(this, SquadVpnService.ACTION_STOP)

    @Composable
    private fun App() {
        var tab by rememberSaveable { mutableIntStateOf(0) }
        var profile by remember { mutableStateOf(Profile.current) }
        var selected by remember { mutableStateOf(Prefs.selectedNode) }
        var refreshing by remember { mutableStateOf(false) }
        var refreshNote by remember { mutableStateOf<String?>(null) }
        var showEvents by rememberSaveable { mutableStateOf(false) }
        var showApps by rememberSaveable { mutableStateOf(false) }
        var appsChanged by remember { mutableStateOf(false) }
        val status by Vpn.status.collectAsStateWithLifecycle()
        val update by Updater.state.collectAsStateWithLifecycle()
        val events by Vpn.events.collectAsStateWithLifecycle()
        val scope = rememberCoroutineScope()
        val snackbar = remember { SnackbarHostState() }
        val backdrop = rememberBackdrop()

        fun refresh(p: Profile, quiet: Boolean = false) {
            refreshing = true
            refreshNote = null
            scope.launch {
                val result = withContext(Dispatchers.IO) { runCatching { Subscriptions.refresh(p) } }
                refreshing = false
                result.onSuccess {
                    Vpn.setNodes(it)
                    refreshNote = "загружено ${it.size} серверов"
                }.onFailure {
                    refreshNote = "не загрузилась"
                    if (!quiet) snackbar.showSnackbar("Подписка не загрузилась: ${it.message}")
                }
            }
        }

        fun changeProfile(p: Profile) {
            if (p == profile) return
            profile = p
            Prefs.profile = p.id
            Prefs.selectedNode = null
            selected = null
            scope.launch {
                val cached = withContext(Dispatchers.IO) { Subscriptions.cached(p) }
                Vpn.setNodes(cached)
                if (cached.isEmpty() && (p != Profile.CUSTOM || Prefs.customUrl.isNotEmpty())) refresh(p)
            }
            // A running VPN moves to the new profile right away.
            if (status == Status.Connected || status == Status.Connecting) {
                disconnect()
                scope.launch {
                    val after = Vpn.status.first { it == Status.Disconnected || it == Status.Failed }
                    if (after == Status.Disconnected) connect()
                }
            }
        }

        LaunchedEffect(Unit) {
            // A fresh list on every start; the saved or built-in copy stays if the network says no.
            val p = Profile.current
            val old = System.currentTimeMillis() - Subscriptions.updatedAt(p) > 10 * 60 * 1000L
            if (old && p != Profile.CUSTOM && Vpn.status.value != Status.Connecting) refresh(p, quiet = Vpn.nodes.value.isNotEmpty())
        }

        // The page under the bars: it starts below the top bar and ends above the floating navigation.
        val top = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
        val bottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
        fun startUpdate() {
            when (val s = Updater.state.value) {
                is Updater.State.Ready -> Updater.install(this@MainActivity, s.file)
                else -> {
                    val info = Updater.available() ?: return
                    scope.launch {
                        Updater.download(info)
                        // Straight on to the installer once the file is here and checked.
                        (Updater.state.value as? Updater.State.Ready)?.let { Updater.install(this@MainActivity, it.file) }
                    }
                }
            }
        }

        LaunchedEffect(updateRequested, update) {
            if (updateRequested && Updater.available() != null) {
                updateRequested = false
                startUpdate()
            }
        }

        val bannerShown = Updater.hasUpdate
        val bannerSpace by animateDpAsState(
            if (bannerShown) UpdateBannerHeight + GlassSpacing.xs else 0.dp,
            GlassSpring.spatial(),
            label = "bannerSpace",
        )
        val contentPadding = PaddingValues(
            top = top + GlassSize.topBar + bannerSpace,
            bottom = bottom + GlassSize.navBar + GlassSize.navMargin * 2 + GlassSpacing.xs,
        )

        CompositionLocalProvider(LocalBackdrop provides backdrop, LocalContentColor provides GlassColors.onGlass) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(GlassColors.backdropBottom),
            ) {
                GlassBackground(backdrop)

                AnimatedContent(
                    targetState = tab,
                    transitionSpec = {
                        val direction = if (targetState > initialState) 1 else -1
                        (
                            slideInHorizontally(GlassSpring.spatial()) { it / 5 * direction } +
                                fadeIn(tween(GlassDuration.medium, easing = GlassEasing.standard)) +
                                scaleIn(GlassSpring.spatial(), initialScale = 0.98f)
                            ).togetherWith(
                            slideOutHorizontally(GlassSpring.spatial()) { -it / 5 * direction } +
                                fadeOut(tween(GlassDuration.short, easing = GlassEasing.standard)),
                        )
                    },
                    label = "tabs",
                ) { page ->
                    Box(Modifier.fillMaxSize()) {
                        when (page) {
                            0 -> ConnectScreen(
                                profile = profile,
                                onProfile = ::changeProfile,
                                onPower = {
                                    when (status) {
                                        Status.Connected, Status.Connecting -> disconnect()
                                        else -> connect()
                                    }
                                },
                                onFailover = { SquadVpnService.send(this@MainActivity, SquadVpnService.ACTION_FAILOVER) },
                                onOpenEvents = { showEvents = true },
                                contentPadding = contentPadding,
                                modifier = Modifier.fillMaxSize(),
                            )
                            1 -> NodesScreen(
                                profile = profile,
                                selected = selected,
                                onSelect = { key ->
                                    selected = key
                                    Prefs.selectedNode = key
                                    if (status == Status.Connected) {
                                        SquadVpnService.send(this@MainActivity, SquadVpnService.ACTION_SWITCH)
                                    }
                                },
                                onPingAll = {
                                    if (!Vpn.pinging.value) scope.launch(Dispatchers.IO) {
                                        Vpn.setPinging(true)
                                        try {
                                            Pinger.pingAll(Vpn.nodes.value)
                                        } finally {
                                            Vpn.setPinging(false)
                                        }
                                    }
                                },
                                contentPadding = contentPadding,
                                modifier = Modifier.fillMaxSize(),
                            )
                            else -> SettingsScreen(
                                profile = profile,
                                onProfile = ::changeProfile,
                                refreshing = refreshing,
                                refreshNote = refreshNote,
                                onRefresh = { refresh(profile) },
                                onOpenApps = { showApps = true },
                                contentPadding = contentPadding,
                                modifier = Modifier.fillMaxSize(),
                            )
                        }
                    }
                }

                AnimatedVisibility(
                    visible = bannerShown,
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = top + GlassSize.topBar)
                        .padding(horizontal = GlassSpacing.md),
                    enter = slideInVertically(GlassSpring.spatial()) { -it } + fadeIn(tween(GlassDuration.medium)),
                    exit = slideOutVertically(tween(GlassDuration.medium, easing = GlassEasing.emphasizedAccelerate)) { -it } +
                        fadeOut(tween(GlassDuration.short)),
                ) {
                    UpdateBanner(state = update, onUpdate = ::startUpdate)
                }

                GlassTopBar(Modifier.align(Alignment.TopCenter)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Image(
                            painterResource(R.drawable.squad_logo),
                            contentDescription = "Логотип SQUAD",
                            modifier = Modifier
                                .size(32.dp)
                                .clip(CircleShape),
                        )
                        Spacer(Modifier.width(GlassSpacing.sm))
                        Text("SQUAD VPN", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                    }
                }

                GlassNavBar(
                    items = listOf(
                        GlassNavItem("VPN", Icons.Rounded.PowerSettingsNew),
                        GlassNavItem("Серверы", Icons.Rounded.Dns),
                        GlassNavItem(
                            "Настройки",
                            Icons.Rounded.Settings,
                            badge = update is Updater.State.Available || update is Updater.State.Ready,
                        ),
                    ),
                    selected = tab,
                    onSelect = {
                        if (it != tab) backdrop.scroll = 0f
                        tab = it
                    },
                    modifier = Modifier.align(Alignment.BottomCenter),
                )

                GlassSnackbarHost(
                    snackbar,
                    Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = contentPadding.calculateBottomPadding()),
                )

                GlassSheet(
                    visible = showApps,
                    onDismiss = {
                        showApps = false
                        // A running VPN picks up the new list at once.
                        if (appsChanged && status == Status.Connected) {
                            SquadVpnService.send(this@MainActivity, SquadVpnService.ACTION_RELOAD_APPS)
                        }
                        appsChanged = false
                    },
                    title = "Приложения без VPN",
                ) {
                    DirectAppsList(onChange = { appsChanged = true })
                }

                GlassSheet(visible = showEvents, onDismiss = { showEvents = false }, title = "События") {
                    LazyColumn(Modifier.heightIn(max = 420.dp)) {
                        items(events) {
                            Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = GlassSpacing.xxs))
                        }
                    }
                }

            }
        }
    }

    companion object {
        const val EXTRA_CONNECT = "connect"
    }
}
