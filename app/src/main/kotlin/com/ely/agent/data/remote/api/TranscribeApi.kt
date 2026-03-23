package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.TranscribeResponse
import okhttp3.MultipartBody
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part

interface TranscribeApi {
    @Multipart
    @POST("api/transcribe")
    suspend fun transcribe(@Part file: MultipartBody.Part): TranscribeResponse
}
