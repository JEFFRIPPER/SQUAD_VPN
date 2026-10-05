package com.squad.vpn.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Dns
import androidx.compose.material.icons.rounded.PowerSettingsNew
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import com.squad.vpn.bg.SquadVpnService
import com.squad.vpn.core.Pinger
import com.squad.vpn.core.Prefs
import com.squad.vpn.core.Profile
import com.squad.vpn.core.Status
import com.squad.vpn.core.Subscriptions
import com.squad.vpn.core.Updater
import com.squad.vpn.core.Vpn
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
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        lifecycleScope.launch(Dispatchers.IO) {
            if (Vpn.nodes.value.isEmpty()) Vpn.setNodes(Subscriptions.cached(Profile.current))
            Updater.checkIfDue()
        }
        val wantsConnect = intent?.getBooleanExtra(EXTRA_CONNECT, false) == true
        if (savedInstanceState == null && (wantsConnect || Prefs.autoConnect) && Vpn.status.value == Status.Disconnected) {
            connect()
        }

        setContent {
            SquadTheme { App() }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getBooleanExtra(EXTRA_CONNECT, false) && Vpn.status.value != Status.Connected) connect()
    }

    fun connect() {
        val prepare = VpnService.prepare(this)
        if (prepare != null) vpnPermission.launch(prepare) else SquadVpnService.send(this, SquadVpnService.ACTION_START)
    }

    fun disconnect() = SquadVpnService.send(this, SquadVpnService.ACTION_STOP)

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    private fun App() {
        var tab by rememberSaveable { mutableStateOf(0) }
        var profile by remember { mutableStateOf(Profile.current) }
        var selected by remember { mutableStateOf(Prefs.selectedNode) }
        var refreshing by remember { mutableStateOf(false) }
        var refreshNote by remember { mutableStateOf<String?>(null) }
        val status by Vpn.status.collectAsStateWithLifecycle()
        val update by Updater.state.collectAsStateWithLifecycle()
        val scope = rememberCoroutineScope()
        val snackbar = remember { SnackbarHostState() }

        fun refresh(p: Profile) {
            refreshing = true
            refreshNote = null
            scope.launch {
                val result = withContext(Dispatchers.IO) { runCatching { Subscriptions.refresh(p) } }
                refreshing = false
                result.onSuccess {
                    Vpn.setNodes(it)
                    refreshNote = "загружено ${it.size} узлов"
                }.onFailure {
                    refreshNote = "не загрузилась"
                    snackbar.showSnackbar("Подписка не загрузилась: ${it.message}")
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
            if (status == Status.Connected) {
                disconnect()
                scope.launch {
                    Vpn.status.first { it == Status.Disconnected }
                    connect()
                }
            }
        }

        LaunchedEffect(Unit) {
            val p = Profile.current
            if (Subscriptions.cached(p).isEmpty() && p != Profile.CUSTOM) refresh(p)
        }

        Scaffold(
            topBar = {
                CenterAlignedTopAppBar(
                    title = { Text("SQUAD VPN", fontWeight = FontWeight.SemiBold) },
                    colors = TopAppBarDefaults.centerAlignedTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
                )
            },
            bottomBar = {
                NavigationBar(containerColor = MaterialTheme.colorScheme.surfaceContainerLow) {
                    NavigationBarItem(
                        selected = tab == 0,
                        onClick = { tab = 0 },
                        icon = { Icon(Icons.Rounded.PowerSettingsNew, null) },
                        label = { Text("VPN") },
                    )
                    NavigationBarItem(
                        selected = tab == 1,
                        onClick = { tab = 1 },
                        icon = { Icon(Icons.Rounded.Dns, null) },
                        label = { Text("Узлы") },
                    )
                    NavigationBarItem(
                        selected = tab == 2,
                        onClick = { tab = 2 },
                        icon = {
                            BadgedBox(badge = {
                                if (update is Updater.State.Available || update is Updater.State.Ready) Badge()
                            }) { Icon(Icons.Rounded.Settings, null) }
                        },
                        label = { Text("Настройки") },
                    )
                }
            },
            snackbarHost = { SnackbarHost(snackbar) },
            containerColor = MaterialTheme.colorScheme.surface,
        ) { padding ->
            AnimatedContent(
                targetState = tab,
                transitionSpec = {
                    val direction = if (targetState > initialState) 1 else -1
                    (slideInHorizontally(Motion.gentle()) { it / 4 * direction } + fadeIn(tween(220)))
                        .togetherWith(slideOutHorizontally(Motion.gentle()) { -it / 4 * direction } + fadeOut(tween(120)))
                },
                modifier = Modifier.padding(padding),
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
                                scope.launch(Dispatchers.IO) {
                                    Vpn.setPinging(true)
                                    try {
                                        Pinger.pingAll(Vpn.nodes.value)
                                    } finally {
                                        Vpn.setPinging(false)
                                    }
                                }
                            },
                            modifier = Modifier.fillMaxSize(),
                        )
                        else -> SettingsScreen(
                            profile = profile,
                            onProfile = ::changeProfile,
                            refreshing = refreshing,
                            refreshNote = refreshNote,
                            onRefresh = { refresh(profile) },
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
            }
        }
    }

    companion object {
        const val EXTRA_CONNECT = "connect"
    }
}
