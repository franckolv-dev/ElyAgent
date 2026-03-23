package com.ely.agent.data.repository

import com.ely.agent.core.network.NetworkResult
import kotlinx.coroutines.flow.Flow

interface AuthRepository {
    suspend fun login(email: String, password: String): NetworkResult<Unit>
    suspend fun logout()
    fun isLoggedIn(): Flow<Boolean>
}
