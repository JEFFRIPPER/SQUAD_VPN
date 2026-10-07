package com.squad.vpn.core

import android.content.Context
import android.content.SharedPreferences
import java.security.SecureRandom
import java.util.Base64

/** Small settings; everything else is derived or cached in files. */
object Prefs {
    private lateinit var sp: SharedPreferences

    fun init(context: Context) {
        sp = context.getSharedPreferences("squad", Context.MODE_PRIVATE)
    }

    var profile: String
        get() = sp.getString("profile", Profile.TOP.id) ?: Profile.TOP.id
        set(value) = sp.edit().putString("profile", value).apply()

    var customUrl: String
        get() = sp.getString("custom_url", "") ?: ""
        set(value) = sp.edit().putString("custom_url", value.trim()).apply()

    /** Key of the node picked by hand; null = automatic choice. */
    var selectedNode: String?
        get() = sp.getString("selected_node", null)
        set(value) = sp.edit().putString("selected_node", value).apply()

    /** The node the VPN last connected to: tried first next time while it answers. */
    var lastGood: String?
        get() = sp.getString("last_good", null)
        set(value) = sp.edit().putString("last_good", value).apply()

    /** The node that worked on [network] ([NetworkId]); on a network seen first, the last one anywhere. */
    fun lastGoodOn(network: String): String? =
        goodByNetwork()[network] ?: lastGood

    fun setLastGoodOn(network: String, key: String) {
        lastGood = key
        if (network.isEmpty()) return
        // Insertion order: the oldest networks drop out first.
        val map = LinkedHashMap(goodByNetwork())
        map.remove(network)
        map[network] = key
        while (map.size > MAX_NETWORKS) map.remove(map.keys.first())
        val json = org.json.JSONObject()
        map.forEach { (net, node) -> json.put(net, node) }
        sp.edit().putString("last_good_by_network", json.toString()).apply()
    }

    private fun goodByNetwork(): Map<String, String> = runCatching {
        val json = org.json.JSONObject(sp.getString("last_good_by_network", null) ?: return emptyMap())
        val map = LinkedHashMap<String, String>()
        for (net in json.keys()) map[net] = json.getString(net)
        map
    }.getOrDefault(emptyMap())

    private const val MAX_NETWORKS = 20

    /** Nodes list: hide nodes that did not answer the last check. */
    var hideDead: Boolean
        get() = sp.getBoolean("hide_dead", true)
        set(value) = sp.edit().putBoolean("hide_dead", value).apply()

    /** "Только эти через VPN": [vpnApps] go through the VPN, everything else goes straight. */
    var onlyApps: Boolean
        get() = sp.getBoolean("only_apps", false)
        set(value) = sp.edit().putBoolean("only_apps", value).apply()

    /** The apps of the [onlyApps] mode. */
    var vpnApps: Set<String>
        get() = sp.getStringSet("vpn_apps", null)?.toSet() ?: emptySet()
        set(value) = sp.edit().putStringSet("vpn_apps", value).apply()

    /** Apps that bypass the VPN; null = [DirectApps.PRESET] (the user never changed the list). */
    var directApps: Set<String>?
        get() = sp.getStringSet("direct_apps", null)?.toSet()
        set(value) = sp.edit().putStringSet("direct_apps", value).apply()

    /** GitHub token the phone probe publishes its checks with; empty = off. */
    var probeToken: String
        get() = sp.getString("probe_token", "") ?: ""
        set(value) = sp.edit().putString("probe_token", value.trim()).apply()

    var probeEnabled: Boolean
        get() = sp.getBoolean("probe_enabled", false)
        set(value) = sp.edit().putBoolean("probe_enabled", value).apply()

    /** Random probe id of this phone, "mobile-<6 hex>"; it names its branch probe-<id>. */
    val probeId: String
        get() = sp.getString("probe_id", null) ?: run {
            val bytes = ByteArray(3).also { SecureRandom().nextBytes(it) }
            ("mobile-" + bytes.joinToString("") { "%02x".format(it) }).also {
                sp.edit().putString("probe_id", it).apply()
            }
        }

    /** When the phone probe last published a report (ms), and what happened last time. */
    var probeLastReport: Long
        get() = sp.getLong("probe_last_report", 0)
        set(value) = sp.edit().putLong("probe_last_report", value).apply()

    var probeNote: String
        get() = sp.getString("probe_note", "") ?: ""
        set(value) = sp.edit().putString("probe_note", value).apply()

    var ruDirect: Boolean
        get() = sp.getBoolean("ru_direct", true)
        set(value) = sp.edit().putBoolean("ru_direct", value).apply()

    /** Cut the TLS handshake into pieces on the way to the server (XrayConfig fragment). */
    var antiDpi: Boolean
        get() = sp.getBoolean("anti_dpi", false)
        set(value) = sp.edit().putBoolean("anti_dpi", value).apply()

    /** Kill switch: when the connection breaks, apps get no internet past the VPN until it is back or turned off. */
    var killSwitch: Boolean
        get() = sp.getBoolean("kill_switch", false)
        set(value) = sp.edit().putBoolean("kill_switch", value).apply()

    var autoConnect: Boolean
        get() = sp.getBoolean("auto_connect", false)
        set(value) = sp.edit().putBoolean("auto_connect", value).apply()

    /** The VPN was on when the phone switched off / the app was updated. */
    var wasConnected: Boolean
        get() = sp.getBoolean("was_connected", false)
        set(value) = sp.edit().putBoolean("was_connected", value).apply()

    /** versionCode the user was last notified about, so each version is announced once. */
    var notifiedVersion: Int
        get() = sp.getInt("notified_version", 0)
        set(value) = sp.edit().putInt("notified_version", value).apply()

    var lastUpdateCheck: Long
        get() = sp.getLong("last_update_check", 0)
        set(value) = sp.edit().putLong("last_update_check", value).apply()

    /** Xray's xudp base key: 32 random bytes, base64url without padding. */
    val deviceKey: String
        get() = sp.getString("xudp_key", null) ?: run {
            val bytes = ByteArray(32).also { SecureRandom().nextBytes(it) }
            Base64.getUrlEncoder().withoutPadding().encodeToString(bytes).also {
                sp.edit().putString("xudp_key", it).apply()
            }
        }
}
