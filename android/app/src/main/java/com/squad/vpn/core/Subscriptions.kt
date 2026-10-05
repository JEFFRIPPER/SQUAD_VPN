package com.squad.vpn.core

import com.squad.vpn.App
import java.io.File

/** Downloads a profile's subscription and keeps the last good copy on disk. */
object Subscriptions {
    private const val STALE_MS = 60 * 60 * 1000L

    private fun file(profile: Profile) = File(App.context.filesDir, "subs/${profile.id}.txt")

    fun updatedAt(profile: Profile): Long = file(profile).takeIf { it.exists() }?.lastModified() ?: 0

    fun cached(profile: Profile): List<Node> =
        file(profile).takeIf { it.exists() }?.let { Links.parseSubscription(it.readText()) }.orEmpty()

    /** Fresh copy from the network; throws when nothing usable came back. */
    fun refresh(profile: Profile): List<Node> {
        val urls = profile.urls
        if (urls.isEmpty()) throw IllegalStateException("Укажи ссылку на подписку в настройках")
        val text = Http.getText(urls)
        val nodes = Links.parseSubscription(text)
        if (nodes.isEmpty()) throw IllegalStateException("В подписке нет подходящих узлов")
        file(profile).apply {
            parentFile?.mkdirs()
            writeText(text)
        }
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
                Vpn.event("Подписка не обновилась, беру сохранённую: ${e.message}")
            }
        }
        return cached
    }
}
