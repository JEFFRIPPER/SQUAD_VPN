package com.squad.vpn.core

import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * The subscriptions CI bundles into the apk (assets/subs) must give the app
 * servers it can use. Local builds without the files skip this test.
 */
class BundledSubscriptionsTest {
    @Test
    fun bundledSubscriptionsParse() {
        val files = File("src/main/assets/subs").listFiles { f -> f.name.endsWith(".b64") }.orEmpty()
        assumeTrue("no bundled subscriptions", files.isNotEmpty())
        for (file in files) {
            val nodes = Links.parseSubscription(file.readText())
            assertTrue("${file.name}: no servers the app can use", nodes.isNotEmpty())
            for (node in nodes) JSONObject(XrayConfig.vpn(node, ruDirect = true))
        }
    }
}
