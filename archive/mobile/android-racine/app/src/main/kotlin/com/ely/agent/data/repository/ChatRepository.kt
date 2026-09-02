package com.ely.agent.data.repository

import com.ely.agent.core.model.Message
import com.ely.agent.data.remote.websocket.ChatWebSocketClient
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

interface ChatRepository {
    val wsConnectionState: StateFlow<ChatWebSocketClient.ConnectionState>
    fun observeMessages(): Flow<List<Message>>
    fun connect()
    suspend fun sendMessage(text: String)
    fun sendHitlResponse(actionId: String, decision: String)
    fun disconnect()
}
