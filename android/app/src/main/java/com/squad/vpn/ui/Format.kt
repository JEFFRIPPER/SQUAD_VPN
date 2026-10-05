package com.squad.vpn.ui

import java.util.Locale

fun formatBytes(bytes: Long): String {
    val units = listOf("Б", "КБ", "МБ", "ГБ", "ТБ")
    var value = bytes.toDouble()
    var unit = 0
    while (value >= 1024 && unit < units.lastIndex) {
        value /= 1024
        unit++
    }
    return if (unit == 0) "${bytes} Б" else String.format(Locale.ROOT, "%.1f %s", value, units[unit])
}

fun formatSpeed(bytesPerSecond: Long): String = "${formatBytes(bytesPerSecond)}/с"

fun formatDuration(ms: Long): String {
    val total = ms / 1000
    val h = total / 3600
    val m = total % 3600 / 60
    val s = total % 60
    return if (h > 0) String.format(Locale.ROOT, "%d:%02d:%02d", h, m, s) else String.format(Locale.ROOT, "%02d:%02d", m, s)
}

fun formatAgo(time: Long): String {
    if (time <= 0) return "ещё не загружалась"
    val minutes = (System.currentTimeMillis() - time) / 60_000
    return when {
        minutes < 1 -> "только что"
        minutes < 60 -> "$minutes мин назад"
        minutes < 48 * 60 -> "${minutes / 60} ч назад"
        else -> "${minutes / 1440} дн назад"
    }
}
