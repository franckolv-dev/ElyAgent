package com.ely.agent.ui.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ely.agent.core.model.HitlRequest
import com.ely.agent.core.model.Message
import com.ely.agent.core.model.MessageRole
import com.ely.agent.data.remote.websocket.ChatWebSocketClient
import com.ely.agent.data.remote.websocket.WsMessage
import com.ely.agent.data.repository.ChatRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val streamingContent: String = "",
    val isStreaming: Boolean = false,
    val inputText: String = "",
    val isLoading: Boolean = false,
    val connectionState: ChatWebSocketClient.ConnectionState = ChatWebSocketClient.ConnectionState.Disconnected()
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val wsClient: ChatWebSocketClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    init {
        chatRepository.connect()
        viewModelScope.launch {
            chatRepository.observeMessages().collect { messages ->
                _uiState.update { it.copy(messages = messages) }
            }
        }
        viewModelScope.launch {
            wsClient.messages.collect { msg ->
                when (msg) {
                    is WsMessage.Start -> _uiState.update { it.copy(isStreaming = true, streamingContent = "") }
                    is WsMessage.Token -> _uiState.update { it.copy(streamingContent = it.streamingContent + msg.content) }
                    is WsMessage.MessageComplete -> _uiState.update { it.copy(isStreaming = false, streamingContent = "") }
                    is WsMessage.HitlPending -> {
                        val hitl = Message(
                            id = "hitl_${msg.actionId}", conversationId = "",
                            role = MessageRole.HITL_PENDING, content = msg.description,
                            hitlRequest = HitlRequest(msg.actionId, msg.tool, msg.description, msg.args)
                        )
                        _uiState.update { it.copy(messages = it.messages + hitl) }
                    }
                    else -> Unit
                }
            }
        }
        viewModelScope.launch {
            chatRepository.wsConnectionState.collect { s ->
                _uiState.update { it.copy(connectionState = s) }
                // Auto-reconnect on disconnect after 3s
                if (s is ChatWebSocketClient.ConnectionState.Disconnected) {
                    delay(3_000)
                    val current = chatRepository.wsConnectionState.value
                    if (current is ChatWebSocketClient.ConnectionState.Disconnected) {
                        chatRepository.connect()
                    }
                }
            }
        }
    }

    fun onInputChange(text: String) = _uiState.update { it.copy(inputText = text) }

    fun sendMessage() {
        val text = _uiState.value.inputText.trim()
        if (text.isBlank()) return
        _uiState.update { it.copy(inputText = "", isLoading = true) }
        viewModelScope.launch {
            chatRepository.sendMessage(text)
            _uiState.update { it.copy(isLoading = false) }
        }
    }

    fun resolveHitl(actionId: String, decision: String) {
        chatRepository.sendHitlResponse(actionId, decision)
        _uiState.update { s -> s.copy(messages = s.messages.filter { it.id != "hitl_$actionId" }) }
    }

    override fun onCleared() { super.onCleared(); chatRepository.disconnect() }
}
