// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/api/ConversationsApi.kt
// @brief      Conversations REST API — list, load history
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
// @version    1.1.0
// =============================================================================

package com.ely.agent.data.remote.api

import com.squareup.moshi.JsonClass
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Query

@JsonClass(generateAdapter = true)
data class ConversationDto(
    val id: String,
    val title: String?,
    val created_at: String?,
    val updated_at: String?,
)

@JsonClass(generateAdapter = true)
data class MessageDto(
    val id: String?,
    val role: String,
    val content: String,
    val created_at: String?,
)

@JsonClass(generateAdapter = true)
data class ConversationDetailDto(
    val id: String,
    val title: String?,
    val messages: List<MessageDto> = emptyList(),
)

interface ConversationsApi {
    @GET("api/conversations")
    suspend fun list(@Query("limit") limit: Int = 50): List<ConversationDto>

    @GET("api/conversations/{id}")
    suspend fun get(@Path("id") id: String): ConversationDetailDto
}
