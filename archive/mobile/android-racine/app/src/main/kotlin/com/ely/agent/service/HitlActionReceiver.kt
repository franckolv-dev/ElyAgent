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
