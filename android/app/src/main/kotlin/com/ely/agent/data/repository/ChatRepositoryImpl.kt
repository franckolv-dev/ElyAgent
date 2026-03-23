package com.ely.agent.data.repository

import com.ely.agent.core.database.dao.MessageDao
import com.ely.agent.core.database.entity.MessageEntity
import com.ely.agent.core.model.Message
import com.ely.agent.core.model.MessageRole
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
    private val messageDao: MessageDao
) : ChatRepository {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var currentConversationId: String = UUID.randomUUID().toString()

    override val wsConnectionState: StateFlow<ChatWebSocketClient.ConnectionState> =
        wsClient.connectionState

    init {
        scope.launch {
            wsClient.messages.collect { msg ->
                if (msg is WsMessage.MessageComplete) {
                    messageDao.insertMessage(
                        MessageEntity(
                            id = msg.id,
                            conversationId = msg.conversationId ?: currentConversationId,
                            role = MessageRole.ASSISTANT.name,
                            content = msg.content,
                            timestamp = System.currentTimeMillis()
                        )
                    )
                }
            }
        }
    }

    override fun observeMessages(conversationId: String): Flow<List<Message>> =
        messageDao.observeMessages(conversationId).map { it.map { e -> e.toDomain() } }

    override fun connect() = wsClient.connect()

    override suspend fun sendMessage(text: String) {
        messageDao.insertMessage(
            MessageEntity(
                id = UUID.randomUUID().toString(),
                conversationId = currentConversationId,
                role = MessageRole.USER.name,
                content = text,
                timestamp = System.currentTimeMillis()
            )
        )
        wsClient.send(text)
    }

    override fun sendHitlResponse(actionId: String, decision: String) =
        wsClient.sendHitlResponse(actionId, decision)

    override fun disconnect() = wsClient.disconnect()

    private fun MessageEntity.toDomain() = Message(
        id = id, conversationId = conversationId,
        role = MessageRole.valueOf(role), content = content, timestamp = timestamp
    )
}
