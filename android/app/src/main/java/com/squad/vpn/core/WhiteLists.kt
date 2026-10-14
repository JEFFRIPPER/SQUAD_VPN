package com.squad.vpn.core

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/**
 * Mobile "white lists": the operator lets through only approved sites.
 * The app is outside its own VPN, so these checks see the real network
 * even while the VPN is on.
 */
object WhiteLists {
    // A site that white lists never let through, and one they always do.
    const val BLOCKED_URL = "https://www.gstatic.com/generate_204"
    const val ALLOWED_URL = "https://ya.ru/"

    fun onMobile(context: Context): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
    }

    /** Approved sites open, everything else does not. Blocking, up to a few seconds. */
    fun on(timeoutMs: Int = 4_000): Boolean =
        !Http.reachableDirect(BLOCKED_URL, timeoutMs) && Http.reachableDirect(ALLOWED_URL, timeoutMs)

    /**
     * Nothing opens straight from the phone, not even the white-listed site:
     * no internet at all (a lift, no signal), so another server would not
     * help and every one would only look dead.
     */
    fun offline(): Boolean = !Http.reachableDirect(ALLOWED_URL, 4_000) && !Http.reachableDirect(BLOCKED_URL, 4_000)

    /** Mobile internet cut down to white lists right now. */
    fun active(context: Context): Boolean = onMobile(context) && on()
}
