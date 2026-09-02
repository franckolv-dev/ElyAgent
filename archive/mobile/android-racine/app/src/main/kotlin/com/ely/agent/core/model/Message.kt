package com.ely.agent.core.model

data class Message(
    val id: String,
    val conversationId: String,
    val role: MessageRole,
    val content: String,
    val streamingContent: String = "",
    val isStreaming: Boolean = false,
    val timestamp: Long = System.currentTimeMillis(),
    val hitlRequest: HitlRequest? = null
)
