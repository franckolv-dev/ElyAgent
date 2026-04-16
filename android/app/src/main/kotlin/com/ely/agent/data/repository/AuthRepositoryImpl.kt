// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/repository/AuthRepositoryImpl.kt
// @brief      Auth repository implementation
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

package com.ely.agent.data.repository

import androidx.datastore.core.DataStore
import com.ely.agent.UserPreferences
import com.ely.agent.core.network.NetworkResult
import com.ely.agent.core.network.safeApiCall
import com.ely.agent.data.remote.api.AuthApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject

class AuthRepositoryImpl @Inject constructor(
    private val authApi: AuthApi,
    private val dataStore: DataStore<UserPreferences>
) : AuthRepository {

    override suspend fun login(email: String, password: String): NetworkResult<Unit> {
        val result = safeApiCall { authApi.login(com.ely.agent.data.remote.dto.LoginRequest(email, password)) }
        if (result is NetworkResult.Success) {
            dataStore.updateData { prefs ->
                prefs.toBuilder().setAccessToken(result.data.accessToken).build()
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
