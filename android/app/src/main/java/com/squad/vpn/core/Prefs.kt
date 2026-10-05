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

    var ruDirect: Boolean
        get() = sp.getBoolean("ru_direct", true)
        set(value) = sp.edit().putBoolean("ru_direct", value).apply()

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
