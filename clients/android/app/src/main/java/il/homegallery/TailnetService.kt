package il.homegallery

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

class TailnetService : Service() {
    private val worker = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private val owner = Any()
    private var destroyed = false
    private val connect = Runnable { connectNode() }

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!TailnetRuntime.keepConnected(this)) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val manager = requireNotNull(getSystemService(NotificationManager::class.java))
        manager.createNotificationChannel(NotificationChannel(
            CHANNEL, getString(R.string.tailnet_channel), NotificationManager.IMPORTANCE_LOW,
        ))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_tailnet_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.tailnet_notification))
            .setContentIntent(open)
            .setOngoing(true)
            .setShowWhen(false)
            .build()
        startForeground(NOTIFICATION_ID, notification)
        handler.removeCallbacks(connect)
        connectNode()
        return START_STICKY
    }

    private fun connectNode() {
        worker.execute {
            val result = runCatching { TailnetRuntime.acquire(applicationContext, owner) }
            if (result.isFailure) handler.post {
                if (!destroyed && TailnetRuntime.keepConnected(this)) {
                    handler.removeCallbacks(connect)
                    handler.postDelayed(connect, 15_000)
                }
            }
        }
    }

    override fun onDestroy() {
        destroyed = true
        handler.removeCallbacksAndMessages(null)
        worker.execute { runCatching { TailnetRuntime.release(owner) } }
        worker.shutdown()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "tailnet-connection"
        private const val NOTIFICATION_ID = 41
    }
}
