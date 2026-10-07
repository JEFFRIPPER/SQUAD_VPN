package com.squad.vpn.core

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Traffic through the VPN by day, kept on the phone for [KEEP_DAYS] days:
 * today, this month and the last week for Settings. Only totals, no sites.
 */
object TrafficStore {
    private const val KEEP_DAYS = 62
    private const val SAVE_EVERY_MS = 30_000L

    /** One day: bytes down and up. */
    data class Day(val date: String, val down: Long, val up: Long) {
        val total: Long get() = down + up
    }

    private lateinit var file: File
    private val days = LinkedHashMap<String, LongArray>()
    private var savedAt = 0L

    private val _version = MutableStateFlow(0L)
    /** Changes whenever totals change: the screen re-reads [today], [month], [lastDays]. */
    val version: StateFlow<Long> = _version.asStateFlow()

    fun init(context: Context) {
        file = File(context.filesDir, "traffic.json")
        runCatching {
            val json = JSONObject(file.readText())
            for (date in json.keys().asSequence().sorted()) {
                val entry = json.getJSONArray(date)
                days[date] = longArrayOf(entry.getLong(0), entry.getLong(1))
            }
        }
    }

    @Synchronized
    fun add(down: Long, up: Long) {
        if (down <= 0 && up <= 0) return
        val entry = days.getOrPut(dateOf(System.currentTimeMillis())) { longArrayOf(0, 0) }
        entry[0] += down
        entry[1] += up
        _version.value++
        val now = System.currentTimeMillis()
        if (now - savedAt >= SAVE_EVERY_MS) save(now)
    }

    /** On disconnect: nothing counted is lost. */
    @Synchronized
    fun flush() = save(System.currentTimeMillis())

    @Synchronized
    fun today(): Day = day(dateOf(System.currentTimeMillis()))

    /** This calendar month. */
    @Synchronized
    fun month(): Day {
        val prefix = dateOf(System.currentTimeMillis()).take(7)
        var down = 0L
        var up = 0L
        days.filterKeys { it.startsWith(prefix) }.values.forEach { down += it[0]; up += it[1] }
        return Day(prefix, down, up)
    }

    /** The last [count] days, oldest first, days without traffic included. */
    @Synchronized
    fun lastDays(count: Int = 7): List<Day> {
        val now = System.currentTimeMillis()
        return (count - 1 downTo 0).map { day(dateOf(now - it * 86_400_000L)) }
    }

    private fun day(date: String): Day = days[date].let { Day(date, it?.get(0) ?: 0, it?.get(1) ?: 0) }

    private fun save(now: Long) {
        if (!::file.isInitialized) return
        savedAt = now
        while (days.size > KEEP_DAYS) days.remove(days.keys.first())
        val json = JSONObject()
        days.forEach { (date, value) -> json.put(date, JSONArray().put(value[0]).put(value[1])) }
        runCatching {
            val tmp = File(file.path + ".tmp")
            tmp.writeText(json.toString())
            tmp.renameTo(file)
        }
    }

    private fun dateOf(time: Long): String = SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).format(Date(time))
}
