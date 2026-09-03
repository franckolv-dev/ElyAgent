// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/api/TranscribeApi.kt
// @brief      Transcription API — speech to text
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

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
