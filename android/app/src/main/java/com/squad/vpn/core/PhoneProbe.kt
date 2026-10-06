package com.squad.vpn.core

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.squad.vpn.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * The phone as a probe for the mobile "white lists": only a phone on mobile
 * internet that is cut down to approved sites sees which servers still work.
 * When that is the case, it checks the "Белые списки" servers straight from
 * that network (the app is outside its own VPN) and publishes the result to
 * the branch probe-<id>, like every SQUAD VPN probe (src/squad_vpn/probe.py).
 * The next subscription update puts the servers that answered first.
 *
 * Off until the user turns it on and pastes a GitHub token: the report is a
 * commit to the repository. It holds only the probe id and per-server
 * results, no phone number, IP or operator.
 */
object PhoneProbe {
    const val KIND = "mobile-whitelist"
    private const val REPORT_EVERY_MS = 60 * 60 * 1000L
    private const val API = "https://api.github.com/repos/${BuildConfig.REPO}"
    private const val SUBS = "${BuildConfig.REPO}@subs"

    // A site that white lists never let through, and one they always do.
    private const val BLOCKED_PROBE_URL = "https://www.gstatic.com/generate_204"
    private const val ALLOWED_PROBE_URL = "https://ya.ru/"

    private val lock = Mutex()
    private val _running = MutableStateFlow(false)
    val running: StateFlow<Boolean> = _running.asStateFlow()
    private val _note = MutableStateFlow(Prefs.probeNote)
    val note: StateFlow<String> = _note.asStateFlow()

    val enabled: Boolean get() = Prefs.probeEnabled && Prefs.probeToken.isNotBlank()

    /** Runs a check when it is due; [force] skips the hourly limit (button in Settings). */
    suspend fun maybeRun(context: Context, force: Boolean = false) {
        if (!enabled) return
        if (!force && System.currentTimeMillis() - Prefs.probeLastReport < REPORT_EVERY_MS) return
        if (!lock.tryLock()) return
        _running.value = true
        try {
            note(run(context, force))
        } catch (e: Exception) {
            note("Ошибка: ${e.message}")
        } finally {
            _running.value = false
            lock.unlock()
        }
    }

    private fun note(text: String) {
        val stamped = "${SimpleDateFormat("dd.MM HH:mm", Locale.getDefault()).format(Date())}: $text"
        Prefs.probeNote = stamped
        _note.value = stamped
    }

    private suspend fun run(context: Context, force: Boolean): String {
        // From the button: say at once whether the token works, so a bad one
        // does not wait unnoticed for the next time white lists come.
        fun idle(text: String) = if (force) "$text. ${tokenStatus()}" else text
        if (!onMobile(context)) return idle("не мобильный интернет, проверка не нужна")
        if (!whiteListsOn()) return idle("белые списки сейчас не включены, проверка не нужна")
        // In white-list mode GitHub opens only through the VPN.
        if (!Vpn.isConnected) return "белые списки включены, но для отправки отчёта включи VPN"

        val nodes = Subscriptions.cached(Profile.WHITELIST)
        if (nodes.isEmpty()) return "нет серверов «Белых списков»"
        val keys = fingerprints()
        val checked = nodes.mapNotNull { node -> keys[Links.linkKey(node.link)]?.let { node to it } }
        if (checked.isEmpty()) return "подписка устарела: обнови «Белые списки»"

        // Straight from this network: exactly what the white lists let through.
        val pings = Pinger.pingAll(checked.map { it.first })
        val now = utc()
        val results = JSONArray()
        for ((node, fp) in checked) {
            val ms = pings[node.key] ?: Pinger.DEAD
            results.put(
                JSONObject()
                    .put("fp", fp)
                    .put("alive", ms > 0)
                    .put("latency_ms", if (ms > 0) ms else JSONObject.NULL)
                    .put("checked_at", now)
                    .put("rate", if (ms > 0) 1.0 else 0.0)
                    .put("checks", 1)
                    .put("error", if (ms > 0) JSONObject.NULL else "timeout"),
            )
        }
        val report = JSONObject()
            .put("format", 1)
            .put("probe_id", Prefs.probeId)
            .put("region", "RU")
            .put("kind", KIND)
            .put("version", "apk-${BuildConfig.VERSION_NAME}")
            .put("generated_at", now)
            .put("results", results)
        publish(report.toString())
        Prefs.probeLastReport = System.currentTimeMillis()
        val alive = pings.values.count { it > 0 }
        return "белые списки включены, отвечают $alive из ${checked.size}, отчёт отправлен"
    }

    private fun tokenStatus(): String =
        try {
            val (code, text) = Http.call("GET", API, null, headers())
            when {
                code == 401 -> "GitHub не принял токен, создай новый"
                code !in 200..299 -> "токен проверить не удалось: GitHub ответил $code"
                JSONObject(text).optJSONObject("permissions")?.optBoolean("push") == true ->
                    "Токен в порядке, проверка запустится сама"
                else -> "у токена нет права писать в репозиторий, создай новый с галочкой public_repo"
            }
        } catch (e: Exception) {
            "токен проверить не удалось: ${e.message}"
        }

    private fun headers() = mapOf(
        "Authorization" to "Bearer ${Prefs.probeToken}",
        "Accept" to "application/vnd.github+json",
        "X-GitHub-Api-Version" to "2022-11-28",
    )

    private fun onMobile(context: Context): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        // The app is outside its own VPN, so this is the real network.
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
    }

    /** Approved sites open, everything else does not. */
    private fun whiteListsOn(): Boolean =
        !Http.reachableDirect(BLOCKED_PROBE_URL) && Http.reachableDirect(ALLOWED_PROBE_URL)

    /** Subscription line key -> server fingerprint, published next to the subscriptions. */
    private fun fingerprints(): Map<String, String> {
        val text = Http.getText(
            listOf(
                "https://raw.githubusercontent.com/${BuildConfig.REPO}/subs/fingerprints.json",
                "https://cdn.jsdelivr.net/gh/$SUBS/fingerprints.json",
            ),
        )
        val json = JSONObject(text)
        return json.keys().asSequence().associateWith { json.getString(it) }
    }

    /**
     * One orphan commit with report.json on branch probe-<id>, replacing the
     * previous one: history does not grow (the same as force-pushing).
     */
    private fun publish(report: String) {
        val headers = headers()
        fun call(method: String, path: String, body: JSONObject?): JSONObject {
            val (code, text) = Http.call(method, "$API$path", body?.toString(), headers)
            if (code == 401) throw IllegalStateException("GitHub не принял токен")
            if (code == 403 || code == 404) throw IllegalStateException("у токена нет права писать в репозиторий")
            if (code !in 200..299) throw IllegalStateException("GitHub ответил $code")
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        }
        val entry = JSONObject().put("path", "report.json").put("mode", "100644").put("type", "blob").put("content", report)
        val tree = call("POST", "/git/trees", JSONObject().put("tree", JSONArray().put(entry))).getString("sha")
        val commit = call(
            "POST",
            "/git/commits",
            JSONObject()
                .put("message", "probe ${Prefs.probeId}: ${utc()} UTC")
                .put("tree", tree)
                .put("parents", JSONArray()),
        ).getString("sha")
        val branch = "probe-${Prefs.probeId}"
        // HttpURLConnection has no PATCH: drop the old branch and create it again.
        runCatching { Http.call("DELETE", "$API/git/refs/heads/$branch", null, headers) }
        call("POST", "/git/refs", JSONObject().put("ref", "refs/heads/$branch").put("sha", commit))
    }

    private fun utc(): String =
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }.format(Date())
}
