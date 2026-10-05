package com.squad.vpn.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import libv2ray.Libv2ray

/** Real-delay test: an HTTPS request through each node in its own small Xray instance. */
object Pinger {
    const val DEAD = -1L

    suspend fun ping(node: Node): Long = withContext(Dispatchers.IO) {
        try {
            val ms = Libv2ray.measureOutboundDelay(XrayConfig.probe(node), XrayConfig.TEST_URL)
            if (ms > 0) ms else DEAD
        } catch (e: Exception) {
            DEAD
        }
    }

    /** Pings [nodes] with limited parallelism, publishing each result as it arrives. */
    suspend fun pingAll(nodes: List<Node>, parallel: Int = 12): Map<String, Long> = coroutineScope {
        val gate = Semaphore(parallel)
        nodes.map { node ->
            async {
                gate.withPermit {
                    val ms = ping(node)
                    Vpn.setPing(node.key, ms)
                    node.key to ms
                }
            }
        }.awaitAll().toMap()
    }
}
