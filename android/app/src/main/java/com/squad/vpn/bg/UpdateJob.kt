package com.squad.vpn.bg

import android.app.NotificationManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.squad.vpn.App
import com.squad.vpn.R
import com.squad.vpn.core.Prefs
import com.squad.vpn.core.Updater
import com.squad.vpn.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Looks for a new app version every few hours, even when the app is closed,
 * and posts a notification once per version. The system runs it only when
 * the phone is online and keeps the schedule across reboots.
 */
class UpdateJob : JobService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var running: Job? = null

    override fun onStartJob(params: JobParameters): Boolean {
        running = scope.launch {
            try {
                Updater.check(quiet = true)
                notifyIfNew(this@UpdateJob)
            } finally {
                jobFinished(params, false)
            }
        }
        return true
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
        private const val JOB_ID = 7001
        private const val NOTIFICATION_ID = 2
        private const val PERIOD_MS = 4 * 60 * 60 * 1000L
        const val EXTRA_UPDATE = "update"

        /** Idempotent: keeps an existing schedule. */
        fun schedule(context: Context) {
            val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
            if (scheduler.getPendingJob(JOB_ID) != null) return
            val job = JobInfo.Builder(JOB_ID, ComponentName(context, UpdateJob::class.java))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(PERIOD_MS)
                .setPersisted(true)
                .build()
            runCatching { scheduler.schedule(job) }
        }

        /** "Доступна версия X": one notification per version; tapping it opens the app on the update. */
        fun notifyIfNew(context: Context) {
            val info = Updater.available() ?: return
            if (Prefs.notifiedVersion == info.versionCode) return
            Prefs.notifiedVersion = info.versionCode
            val open = PendingIntent.getActivity(
                context,
                3,
                Intent(context, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                    .putExtra(EXTRA_UPDATE, true),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            val notification = NotificationCompat.Builder(context, App.CHANNEL_UPDATES)
                .setSmallIcon(R.drawable.ic_shield)
                .setColor(0xFFD00018.toInt())
                .setContentTitle("Доступно обновление SQUAD VPN")
                .setContentText("Версия ${info.versionName}. Нажми, чтобы обновить")
                .setAutoCancel(true)
                .setContentIntent(open)
                .addAction(0, "Обновить", open)
                .build()
            runCatching {
                context.getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification)
            }
        }
    }
}
