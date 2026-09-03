// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/service/ElyFirebaseMessagingService.kt
// @brief      Firebase Cloud Messaging service
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.ely.agent.core.fcm.FcmTokenManager
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class ElyFirebaseMessagingService : FirebaseMessagingService() {

    companion object {
        const val CHANNEL_HITL = "hitl_channel"
        const val EXTRA_ACTION_ID = "action_id"
        const val EXTRA_DECISION = "decision"
    }

    @Inject lateinit var fcmTokenManager: FcmTokenManager
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() { super.onCreate(); createNotificationChannel() }

    /**
     * Fired by Firebase whenever a fresh FCM token is issued (first launch,
     * app reinstall, data wipe, periodic rotation). We push it to the ELY
     * backend if the user is already logged in — otherwise the next
     * successful login will register whatever token Firebase has at that
     * point.
     */
    override fun onNewToken(token: String) {
        scope.launch { fcmTokenManager.registerCurrentToken(explicitToken = token) }
    }

    /**
     * Android can destroy & recreate `FirebaseMessagingService` at any time.
     * Without explicit cleanup, the CoroutineScope would leak each cycle —
     * coroutines launched in `onNewToken` would keep their references alive
     * past the service's lifetime. `scope.cancel()` cooperates with structured
     * concurrency and terminates any pending registration call cleanly.
     */
    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        when (data["type"]) {
            "hitl_pending" -> showHitlNotification(
                data["action_id"] ?: return, data["tool"] ?: "", data["description"] ?: "Action requise"
            )
        }
    }

    private fun showHitlNotification(actionId: String, tool: String, description: String) {
        val approveIntent = Intent(this, HitlActionReceiver::class.java)
            .putExtra(EXTRA_ACTION_ID, actionId).putExtra(EXTRA_DECISION, "allow")
        val denyIntent = Intent(this, HitlActionReceiver::class.java)
            .putExtra(EXTRA_ACTION_ID, actionId).putExtra(EXTRA_DECISION, "deny")
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        val approvePi = PendingIntent.getBroadcast(this, actionId.hashCode() + 1, approveIntent, flags)
        val denyPi = PendingIntent.getBroadcast(this, actionId.hashCode() + 2, denyIntent, flags)

        val notification = NotificationCompat.Builder(this, CHANNEL_HITL)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("ELY demande votre autorisation")
            .setContentText("$tool: $description")
            .setStyle(NotificationCompat.BigTextStyle().bigText("$tool: $description"))
            .setPriority(NotificationCompat.PRIORITY_HIGH).setAutoCancel(true)
            .addAction(android.R.drawable.ic_menu_send, "✓ Approuver", approvePi)
            .addAction(android.R.drawable.ic_delete, "✗ Refuser", denyPi)
            .build()

        NotificationManagerCompat.from(this).notify(actionId.hashCode(), notification)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(CHANNEL_HITL, "Autorisations ELY", NotificationManager.IMPORTANCE_HIGH)
                .apply { description = "Demandes d'autorisation pour les actions sensibles" }
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
        }
    }
}
