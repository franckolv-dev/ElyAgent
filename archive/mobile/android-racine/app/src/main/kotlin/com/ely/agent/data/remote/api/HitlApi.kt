package com.ely.agent.data.remote.api

import retrofit2.Response
import retrofit2.http.POST
import retrofit2.http.Path

interface HitlApi {
    @POST("api/validation/{actionId}/allow")
    suspend fun allow(@Path("actionId") actionId: String): Response<Unit>

    @POST("api/validation/{actionId}/deny")
    suspend fun deny(@Path("actionId") actionId: String): Response<Unit>
}
