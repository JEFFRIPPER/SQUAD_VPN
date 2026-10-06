package com.squad.vpn.core

/** Subscriptions published by SQUAD VPN (branch subs), plus the user's own link. */
enum class Profile(val id: String, val title: String, val hint: String) {
    TOP("top", "Топ-10", "Самые надёжные серверы. Начни с неё"),
    BEST("best", "Лучшие 300", "300 лучших серверов, больше выбор"),
    WHITELIST("whitelist", "Белые списки", "До 100 серверов на случай, когда глушат мобильный интернет. Обнови заранее"),
    CUSTOM("custom", "Своя ссылка", "Любая подписка v2ray / base64");

    val urls: List<String>
        get() = if (this == CUSTOM) {
            listOf(Prefs.customUrl).filter { it.startsWith("http") }
        } else {
            listOf(
                "https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/$id.b64",
                "https://cdn.jsdelivr.net/gh/JEFFRIPPER/SQUAD_VPN@subs/$id.b64",
            )
        }

    companion object {
        fun of(id: String): Profile = entries.firstOrNull { it.id == id } ?: TOP
        val current: Profile get() = of(Prefs.profile)
    }
}
