// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/repository/AuthRepositoryImpl.kt
// @brief      Auth repository implementation
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.repository

import androidx.datastore.core.DataStore
import com.ely.agent.UserPreferences
import com.ely.agent.core.fcm.FcmTokenManager
import com.ely.agent.core.network.NetworkResult
import com.ely.agent.core.network.safeApiCall
import com.ely.agent.data.remote.api.AuthApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import javax.inject.Inject

class AuthRepositoryImpl @Inject constructor(
    private val authApi: AuthApi,
    private val dataStore: DataStore<UserPreferences>,
    private val fcmTokenManager: FcmTokenManager,
) : AuthRepository {

    override suspend fun login(email: String, password: String): NetworkResult<Unit> {
        val result = safeApiCall { authApi.login(com.ely.agent.data.remote.dto.LoginRequest(email, password)) }
        if (result is NetworkResult.Success) {
            dataStore.updateData { prefs ->
                prefs.toBuilder().setAccessToken(result.data.accessToken).build()
            }
            // Register FCM token so HITL push notifications reach this device.
            // Fire-and-forget on a detached application-scoped coroutine so the
            // user-facing login() returns immediately after the access token is
            // persisted — the FCM registration can take several seconds and
            // should NOT block the UI response.
            val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            appScope.launch {
                runCatching { fcmTokenManager.registerCurrentToken() }
                    .onFailure { /* swallow — already logged inside manager */ }
            }
        }
        return when (result) {
            is NetworkResult.Success -> NetworkResult.Success(Unit)
            is NetworkResult.Error -> result
            is NetworkResult.Exception -> result
        }
    }

    override suspend fun logout() {
        dataStore.updateData { it.toBuilder().clearAccessToken().build() }
    }

    override fun isLoggedIn(): Flow<Boolean> =
        dataStore.data.map { it.accessToken.isNotBlank() }
}
