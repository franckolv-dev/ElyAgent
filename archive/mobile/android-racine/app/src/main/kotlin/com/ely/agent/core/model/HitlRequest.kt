package com.ely.agent.core.model

data class HitlRequest(
    val actionId: String,
    val tool: String,
    val description: String,
    val args: Map<String, String> = emptyMap()
)
