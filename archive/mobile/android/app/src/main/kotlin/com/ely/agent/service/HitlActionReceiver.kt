// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/service/HitlActionReceiver.kt
// @brief      HITL notification action receiver
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

package com.ely.agent.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationManagerCompat
import com.ely.agent.data.remote.api.HitlApi
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class HitlActionReceiver : BroadcastReceiver() {
    @Inject lateinit var hitlApi: HitlApi

    override fun onReceive(context: Context, intent: Intent) {
        val actionId = intent.getStringExtra(ElyFirebaseMessagingService.EXTRA_ACTION_ID) ?: return
        val decision = intent.getStringExtra(ElyFirebaseMessagingService.EXTRA_DECISION) ?: return
        NotificationManagerCompat.from(context).cancel(actionId.hashCode())
        CoroutineScope(Dispatchers.IO).launch {
            try { if (decision == "allow") hitlApi.allow(actionId) else hitlApi.deny(actionId) }
            catch (_: Exception) {}
        }
    }
}
