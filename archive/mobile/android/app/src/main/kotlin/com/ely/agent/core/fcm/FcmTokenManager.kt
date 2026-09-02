// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/core/fcm/FcmTokenManager.kt
// @brief      FCM token registration helper — bridges Firebase and backend
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
// =============================================================================

package com.ely.agent.core.fcm

import android.util.Log
import androidx.datastore.core.DataStore
import com.ely.agent.UserPreferences
import com.ely.agent.data.remote.api.DeviceTokenApi
import com.ely.agent.data.remote.dto.DeviceTokenRequest
import com.google.android.gms.tasks.Task
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.suspendCancellableCoroutine
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Registers the current Firebase Cloud Messaging token with the ELY backend
 * so HITL push notifications can reach the device.
 *
 * Call sites:
 *   1. After a successful login (AuthRepositoryImpl.login)
 *   2. Whenever Firebase rotates the token (ElyFirebaseMessagingService.onNewToken)
 *   3. At app cold-start when the user is already logged in (MainActivity)
 *
 * The registration is best-effort: if the network fails or the user is not
 * logged in, we log and move on. The next trigger will retry.
 */
@Singleton
class FcmTokenManager @Inject constructor(
    private val deviceTokenApi: DeviceTokenApi,
    private val dataStore: DataStore<UserPreferences>,
) {
    companion object { private const val TAG = "FcmTokenManager" }

    /**
     * Fetch the current FCM token from Firebase and push it to the backend.
     * No-op if the user has no access token in DataStore.
     *
     * @param explicitToken if provided, skip Firebase lookup — used by
     *                      `onNewToken()` which already has the fresh token.
     */
    suspend fun registerCurrentToken(explicitToken: String? = null) {
        val accessToken = runCatching {
            dataStore.data.first().accessToken
        }.getOrElse { "" }

        if (accessToken.isBlank()) {
            Log.d(TAG, "Skip FCM registration — user not logged in.")
            return
        }

        // Fetch the FCM token. We avoid `runCatching { … }.getOrElse { return }`
        // because the `return` inside `getOrElse` is ambiguous in Kotlin (local
        // return from the lambda vs non-local return from the suspend function).
        // Explicit try/catch with a guaranteed non-null String or early return.
        val fcmToken: String = if (explicitToken != null) {
            explicitToken
        } else {
            try {
                awaitFirebaseToken()
            } catch (e: Exception) {
                Log.w(TAG, "Failed to fetch FCM token from Firebase: ${e.message}")
                return
            }
        }

        if (fcmToken.isBlank()) {
            Log.w(TAG, "Firebase returned an empty FCM token.")
            return
        }

        runCatching {
            val response = deviceTokenApi.registerToken(DeviceTokenRequest(token = fcmToken))
            if (response.isSuccessful) {
                Log.i(TAG, "FCM token registered with backend ✓")
            } else {
                Log.w(TAG, "Backend returned HTTP ${response.code()} when registering FCM token.")
            }
        }.onFailure {
            Log.w(TAG, "Error calling /api/device-token: ${it.message}")
        }
    }

    /** Bridge Firebase's Task<String> into a suspending function. */
    private suspend fun awaitFirebaseToken(): String =
        suspendCancellableCoroutine { cont ->
            FirebaseMessaging.getInstance().token.addOnCompleteListener { task: Task<String> ->
                if (task.isSuccessful) {
                    cont.resume(task.result ?: "")
                } else {
                    cont.resumeWithException(task.exception ?: Exception("Unknown Firebase error"))
                }
            }
        }
}
