package com.ely.agent.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SkillDto(
    val name: String,
    @Json(name = "display_name") val displayName: String,
    val description: String,
    val icon: String = "⚡",
    val enabled: Boolean = true,
    val version: String = "1.0.0"
)
