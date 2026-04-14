package com.ely.agent.data.remote.websocket

sealed class WsMessage {
    data class Start(val conversationId: String? = null) : WsMessage()
    data class Token(val content: String) : WsMessage()
    data class MessageComplete(
        val id: String,
        val content: String,
        val conversationId: String? = null
    ) : WsMessage()
    data class HitlPending(
        val actionId: String,
        val tool: String,
        val description: String,
        val args: Map<String, String> = emptyMap()
    ) : WsMessage()
    data class Error(val message: String) : WsMessage()
    data class Unknown(val raw: String) : WsMessage()
}
