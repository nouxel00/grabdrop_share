package io.github.nouxel00.grabdrop

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper

/**
 * Garde l'app en vie tant qu'un objet est en main, même si l'utilisateur quitte
 * l'app pour aller faire son DROP devant un PC. S'arrête seul ensuite.
 */
class GrabDropService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val runtime get() = (application as GrabDropApp).runtime

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Objet en main", NotificationManager.IMPORTANCE_LOW)
        )
        startForeground(NOTIFICATION_ID, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        handler.removeCallbacksAndMessages(null)
        handler.post(object : Runnable {
            override fun run() {
                if (runtime.held.peek() == null) {
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelf()
                    runtime.maybeStop()
                    return
                }
                getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification())
                handler.postDelayed(this, 1000)
            }
        })
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun notification(): Notification {
        val view = runtime.heldView.value
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("En main : ${view?.description ?: "…"}")
            .setContentText("Faites DROP devant un PC · encore ${view?.remainingS ?: 0} s")
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    companion object {
        private const val CHANNEL = "held"
        private const val NOTIFICATION_ID = 1
    }
}
