// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/service/ElyFirebaseMessagingService.kt
// @brief      Firebase Cloud Messaging service
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
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
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class ElyFirebaseMessagingService : FirebaseMessagingService() {

    companion object {
        const val CHANNEL_HITL = "hitl_channel"
        const val EXTRA_ACTION_ID = "action_id"
        const val EXTRA_DECISION = "decision"
    }

    override fun onCreate() { super.onCreate(); createNotificationChannel() }
    override fun onNewToken(token: String) { /* Registered from MainActivity after login */ }

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
