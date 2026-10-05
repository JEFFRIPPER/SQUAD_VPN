package com.squad.vpn.core

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import com.squad.vpn.App
import com.squad.vpn.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/**
 * Over-the-air updates: CI publishes SQUAD-VPN.apk and android-manifest.json
 * to the release "android-latest"; a newer versionCode is offered in the app,
 * downloaded, checked against its sha256 and handed to the system installer.
 */
object Updater {
    private const val BASE = "https://github.com/${BuildConfig.REPO}/releases/download/android-latest"
    private const val CHECK_EVERY_MS = 6 * 60 * 60 * 1000L

    data class Info(val versionCode: Int, val versionName: String, val sha256: String, val size: Long, val notes: String)

    sealed interface State {
        data object Idle : State
        data object Checking : State
        data object UpToDate : State
        data class Available(val info: Info) : State
        data class Downloading(val info: Info, val progress: Float) : State
        data class Ready(val info: Info, val file: File) : State
        data class Error(val message: String) : State
    }

    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state.asStateFlow()

    private val apk: File get() = File(App.context.cacheDir, "updates/SQUAD-VPN.apk")

    suspend fun checkIfDue() {
        if (System.currentTimeMillis() - Prefs.lastUpdateCheck < CHECK_EVERY_MS) return
        check(quiet = true)
    }

    suspend fun check(quiet: Boolean = false) = withContext(Dispatchers.IO) {
        _state.value = State.Checking
        try {
            val json = JSONObject(Http.getText(listOf("$BASE/android-manifest.json")))
            Prefs.lastUpdateCheck = System.currentTimeMillis()
            val info = Info(
                versionCode = json.getInt("versionCode"),
                versionName = json.optString("versionName"),
                sha256 = json.optString("sha256").lowercase(),
                size = json.optLong("size"),
                notes = json.optString("notes"),
            )
            _state.value = when {
                info.versionCode <= BuildConfig.VERSION_CODE -> State.UpToDate
                apk.exists() && sha256(apk) == info.sha256 -> State.Ready(info, apk)
                else -> State.Available(info)
            }
        } catch (e: Exception) {
            _state.value = if (quiet) State.Idle else State.Error("Не удалось проверить: ${e.message}")
        }
        Unit
    }

    suspend fun download(info: Info) = withContext(Dispatchers.IO) {
        _state.value = State.Downloading(info, 0f)
        try {
            Http.download("$BASE/SQUAD-VPN.apk", apk) { done, total ->
                val size = if (total > 0) total else info.size
                if (size > 0) _state.value = State.Downloading(info, (done.toFloat() / size).coerceIn(0f, 1f))
            }
            if (info.sha256.isNotEmpty() && sha256(apk) != info.sha256) {
                apk.delete()
                throw IllegalStateException("файл повреждён, попробуй ещё раз")
            }
            _state.value = State.Ready(info, apk)
        } catch (e: Exception) {
            _state.value = State.Error("Не удалось скачать: ${e.message}")
        }
        Unit
    }

    /** Opens the system installer; first asks for "install unknown apps" if needed. */
    fun install(context: Context, file: File) {
        val pm = context.packageManager
        if (!pm.canRequestPackageInstalls()) {
            context.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            return
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        context.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                digest.update(buffer, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
