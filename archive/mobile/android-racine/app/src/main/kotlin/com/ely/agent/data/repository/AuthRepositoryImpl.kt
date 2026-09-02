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
