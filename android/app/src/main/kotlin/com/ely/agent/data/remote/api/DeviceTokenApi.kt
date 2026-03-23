package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.DeviceTokenRequest
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.PUT

interface DeviceTokenApi {
    @PUT("api/device-token")
    suspend fun registerToken(@Body body: DeviceTokenRequest): Response<Unit>
}
