package com.squad.vpn.core

import com.squad.vpn.App
import java.io.File

/** Downloads a profile's subscription and keeps the last good copy on disk. */
object Subscriptions {
    const val STALE_MS = 60 * 60 * 1000L

    private fun file(profile: Profile) = File(App.context.filesDir, "subs/${profile.id}.txt")

    /** Drops the saved copy: the next load downloads (or, for inline keys, parses) afresh. */
    fun forget(profile: Profile) {
        file(profile).delete()
    }

    fun updatedAt(profile: Profile): Long = file(profile).takeIf { it.exists() }?.lastModified() ?: 0

    /**
     * The last downloaded copy, or the one built into the app: on a network
     * that lets nothing through but white-listed servers GitHub may never open,
     * and the app must still have nodes to start from.
     */
    fun cached(profile: Profile): List<Node> {
        // A copy that no longer parses (cut short, old format) falls back to the built-in one.
        file(profile).takeIf { it.exists() }
            ?.let { runCatching { Links.parseSubscription(it.readText()) }.getOrNull() }
            ?.takeIf { it.isNotEmpty() }
            ?.let { return it }
        return bundled(profile)
    }

    private fun bundled(profile: Profile): List<Node> =
        runCatching {
            App.context.assets.open("subs/${profile.id}.b64").bufferedReader().use { Links.parseSubscription(it.readText()) }
        }.getOrDefault(emptyList())

    /** Fresh copy from the network; throws when nothing usable came back. */
    fun refresh(profile: Profile): List<Node> {
        val urls = profile.urls
        // "Своя ссылка" may hold the keys themselves (vless://… one per line): nothing to download.
        val inline = profile == Profile.CUSTOM && urls.isEmpty() && Prefs.customUrl.contains("://")
        if (urls.isEmpty() && !inline) throw IllegalStateException("Укажи ссылку на подписку в настройках")
        val text = if (inline) Prefs.customUrl else Http.getText(urls)
        val nodes = Links.parseSubscription(text)
        if (nodes.isEmpty()) throw IllegalStateException("В подписке нет подходящих серверов")
        // Through a temporary file: a background refresh and a connection may read it at the same time.
        val target = file(profile)
        target.parentFile?.mkdirs()
        val tmp = File(target.path + ".tmp")
        tmp.writeText(text)
        if (!tmp.renameTo(target)) target.writeText(text)
        return nodes
    }

    /** Cached nodes, refreshed first when the copy is old; the cache wins if the network fails. */
    fun load(profile: Profile, forceRefresh: Boolean = false): List<Node> {
        val cached = cached(profile)
        val stale = System.currentTimeMillis() - updatedAt(profile) > STALE_MS
        if (cached.isEmpty() || stale || forceRefresh) {
            try {
                return refresh(profile)
            } catch (e: Exception) {
                if (cached.isEmpty()) throw e
                Vpn.event("Подписка не обновилась, беру сохранённую копию: ${e.message}")
            }
        }
        return cached
    }
}
