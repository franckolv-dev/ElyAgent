package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.LoginRequest
import com.ely.agent.data.remote.dto.TokenResponse
import retrofit2.http.Body
import retrofit2.http.POST

interface AuthApi {
    @POST("auth/login")
    suspend fun login(@Body request: LoginRequest): TokenResponse
}
