package com.ely.agent.data.remote.dto

import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class TranscribeResponse(val text: String, val language: String = "fr")
