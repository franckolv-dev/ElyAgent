// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/repository/ChatRepositoryImpl.kt
// @brief      Chat repository implementation — WebSocket + multi-conversations
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
// @version    1.1.0
// =============================================================================

package com.ely.agent.data.repository

import com.ely.agent.core.database.dao.MessageDao
import com.ely.agent.core.database.entity.MessageEntity
import com.ely.agent.core.model.Message
import com.ely.agent.core.model.MessageRole
import com.ely.agent.data.remote.api.ConversationsApi
import com.ely.agent.data.remote.websocket.ChatWebSocketClient
import com.ely.agent.data.remote.websocket.WsMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatRepositoryImpl @Inject constructor(
    private val wsClient: ChatWebSocketClient,
    private val messageDao: MessageDao,
    private val conversationsApi: ConversationsApi,
) : ChatRepository {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var currentConversationId: String = UUID.randomUUID().toString()

    override val wsConnectionState: StateFlow<ChatWebSocketClient.ConnectionState> =
        wsClient.connectionState

    init {
        scope.launch {
            wsClient.messages.collect { msg ->
                if (msg is WsMessage.MessageComplete) {
                    // Backend may have renamed / created the conversation —
                    // adopt the id it returned so the next turn lands in
                    // the same thread on both sides.
                    val convId = msg.conversationId ?: currentConversationId
                    currentConversationId = convId
                    messageDao.insertMessage(
                        MessageEntity(
                            id = msg.id,
                            conversationId = convId,
                            role = MessageRole.ASSISTANT.name,
                            content = msg.content,
                            timestamp = System.currentTimeMillis(),
                        )
                    )
                }
            }
        }
    }

    override fun observeMessages(): Flow<List<Message>> =
        messageDao.observeMessagesForConversation(currentConversationId)
            .map { it.map { e -> e.toDomain() } }

    override fun connect() = wsClient.connect()

    override suspend fun sendMessage(text: String) {
        messageDao.insertMessage(
            MessageEntity(
                id = UUID.randomUUID().toString(),
                conversationId = currentConversationId,
                role = MessageRole.USER.name,
                content = text,
                timestamp = System.currentTimeMillis(),
            )
        )
        // Include the conversationId so the backend continues the same thread
        wsClient.send(text, conversationId = currentConversationId)
    }

    override fun sendHitlResponse(actionId: String, decision: String) =
        wsClient.sendHitlResponse(actionId, decision)

    override fun sendStop() = wsClient.sendStop()

    override fun disconnect() = wsClient.disconnect()

    override fun resetCurrentConversation() {
        currentConversationId = UUID.randomUUID().toString()
    }

    override fun switchConversation(conversationId: String) {
        currentConversationId = conversationId
        // Fetch backend history and upsert into local DB so the UI renders it
        scope.launch {
            try {
                val detail = conversationsApi.get(conversationId)
                for (m in detail.messages) {
                    val role = when (m.role) {
                        "user" -> MessageRole.USER
                        "assistant" -> MessageRole.ASSISTANT
                        else -> continue
                    }
                    messageDao.insertMessage(
                        MessageEntity(
                            id = m.id ?: UUID.randomUUID().toString(),
                            conversationId = conversationId,
                            role = role.name,
                            content = m.content,
                            timestamp = _parseIso(m.created_at) ?: System.currentTimeMillis(),
                        )
                    )
                }
            } catch (_: Exception) {
                // Silent — the UI will just show whatever is in local DB
            }
        }
    }

    override suspend fun listConversations(limit: Int): List<ConversationSummary> {
        return try {
            conversationsApi.list(limit).map {
                ConversationSummary(
                    id = it.id,
                    title = it.title ?: "Conversation",
                    createdAt = it.created_at,
                    updatedAt = it.updated_at,
                )
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    private fun _parseIso(iso: String?): Long? {
        if (iso.isNullOrBlank()) return null
        return try {
            java.time.Instant.parse(if (iso.endsWith("Z")) iso else "${iso}Z").toEpochMilli()
        } catch (_: Exception) {
            try {
                java.time.LocalDateTime.parse(iso.substringBefore('.'))
                    .atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
            } catch (_: Exception) { null }
        }
    }

    private fun MessageEntity.toDomain() = Message(
        id = id, conversationId = conversationId,
        role = MessageRole.valueOf(role), content = content, timestamp = timestamp
    )
}
