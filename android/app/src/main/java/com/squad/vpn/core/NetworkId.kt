package com.squad.vpn.core

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import java.net.Inet4Address

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
                // Two SIMs: the one carrying mobile data, not the default for calls.
                val phone = context.getSystemService(TelephonyManager::class.java)
                val data = SubscriptionManager.getDefaultDataSubscriptionId()
                val operator = (if (data != SubscriptionManager.INVALID_SUBSCRIPTION_ID) phone?.createForSubscriptionId(data) else phone)
                    ?.networkOperator.orEmpty()
                "mobile:$operator"
            }
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> {
                // The IPv4 router: the IPv6 default route's gateway is a link-local address.
                val gateway = cm.getLinkProperties(network)?.routes
                    ?.filter { it.isDefaultRoute }
                    ?.mapNotNull { it.gateway }
                    ?.firstOrNull { it is Inet4Address && !it.isAnyLocalAddress }
                    ?.hostAddress.orEmpty()
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
