package com.squad.vpn.core

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.telephony.TelephonyManager

/**
 * Which network the phone is on, so each one keeps the server that worked
 * there: home Wi-Fi and mobile internet often let through different servers.
 * Needs no permission: the operator code (MCC+MNC) for mobile, the router's
 * address for Wi-Fi. The app is outside its own VPN, so this is the real network.
 */
object NetworkId {
    /** "mobile:25020", "wifi:192.168.1.1", or "" when unknown. */
    fun current(context: Context): String = runCatching {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val network = cm.activeNetwork ?: return ""
        val caps = cm.getNetworkCapabilities(network) ?: return ""
        when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> {
                val operator = context.getSystemService(TelephonyManager::class.java)?.networkOperator.orEmpty()
                "mobile:$operator"
            }
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> {
                val gateway = cm.getLinkProperties(network)?.routes
                    ?.firstOrNull { it.isDefaultRoute && it.gateway != null }
                    ?.gateway?.hostAddress.orEmpty()
                "wifi:$gateway"
            }
            else -> ""
        }
    }.getOrDefault("")

    /** For the event log: "мобильная сеть 25020", "Wi-Fi". */
    fun label(id: String): String = when {
        id.startsWith("mobile:") -> "мобильная сеть ${id.removePrefix("mobile:")}".trim()
        id.startsWith("wifi:") -> "Wi-Fi"
        else -> "сеть"
    }
}
