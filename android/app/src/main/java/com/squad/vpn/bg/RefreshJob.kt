package com.squad.vpn.bg

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import com.squad.vpn.core.Pinger
import com.squad.vpn.core.Profile
import com.squad.vpn.core.Status
import com.squad.vpn.core.Subscriptions
import com.squad.vpn.core.Vpn
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Fresh servers before the user needs them: on Wi-Fi and on the charger,
 * the subscription (and "Белые списки", for the day the operator turns
 * them on) is downloaded and its servers pinged in the background. The
 * next connection starts from a list that is already checked.
 */
class RefreshJob : JobService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var running: Job? = null

    override fun onStartJob(params: JobParameters): Boolean {
        running = scope.launch {
            try {
                refresh()
            } finally {
                jobFinished(params, false)
            }
        }
        return true
    }

    private suspend fun refresh() {
        val profile = Profile.current
        val nodes = runCatching { Subscriptions.refresh(profile) }.getOrElse { Subscriptions.cached(profile) }
        if (profile != Profile.WHITELIST) runCatching { Subscriptions.refresh(Profile.WHITELIST) }
        val status = Vpn.status.value
        // A running VPN keeps the list it runs on.
        if (status == Status.Disconnected || status == Status.Failed) Vpn.setNodes(nodes)
        // A connection being set up pings on its own.
        if (status == Status.Connecting || Vpn.isPinging) return
        val stale = nodes.filter { !Vpn.isFresh(it.key) }
        if (stale.isEmpty()) return
        Pinger.startCheck(stale).join()
        // The pings are saved a few seconds after the last one.
        delay(4_000)
    }

    override fun onStopJob(params: JobParameters): Boolean {
        running?.cancel()
        return true
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val JOB_ID = 7002
        private const val PERIOD_MS = 6 * 60 * 60 * 1000L

        /** Idempotent: keeps an existing schedule. */
        fun schedule(context: Context) {
            val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
            if (scheduler.getPendingJob(JOB_ID) != null) return
            val job = JobInfo.Builder(JOB_ID, ComponentName(context, RefreshJob::class.java))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED)
                .setRequiresCharging(true)
                .setPeriodic(PERIOD_MS)
                .setPersisted(true)
                .build()
            runCatching { scheduler.schedule(job) }
        }
    }
}
