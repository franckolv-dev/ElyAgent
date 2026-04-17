// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/ui/chat/ChatViewModel.kt
// @brief      Chat ViewModel — state management
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

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
import kotlinx.coroutines.Job
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
    val connectionState: ChatWebSocketClient.ConnectionState = ChatWebSocketClient.ConnectionState.Disconnected(),
    /** Currently active conversation id — switches when user picks from the drawer. */
    val currentConversationId: String? = null,
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val wsClient: ChatWebSocketClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    // Safety timer — if no token/message event arrives within 90s while we
    // are "streaming", assume the backend response was lost (disconnection,
    // crash, etc.) and reset isStreaming so the input becomes usable again.
    private var _streamingWatchdog: Job? = null

    init {
        chatRepository.connect()
        viewModelScope.launch {
            chatRepository.observeMessages().collect { messages ->
                _uiState.update { it.copy(messages = messages) }
            }
        }
        viewModelScope.launch {
            wsClient.messages.collect { msg ->
                // Any incoming message resets the watchdog timer
                _streamingWatchdog?.cancel()

                when (msg) {
                    is WsMessage.Start -> {
                        _uiState.update { it.copy(isStreaming = true, streamingContent = "") }
                        _startStreamingWatchdog()
                    }
                    is WsMessage.Token -> {
                        _uiState.update { it.copy(streamingContent = it.streamingContent + msg.content) }
                        _startStreamingWatchdog()
                    }
                    is WsMessage.MessageComplete -> {
                        _uiState.update {
                            it.copy(
                                isStreaming = false,
                                streamingContent = "",
                                isLoading = false,
                            )
                        }
                    }
                    is WsMessage.HitlPending -> {
                        val hitl = Message(
                            id = "hitl_${msg.actionId}",
                            conversationId = _uiState.value.currentConversationId ?: "",
                            role = MessageRole.HITL_PENDING,
                            content = msg.description,
                            hitlRequest = HitlRequest(msg.actionId, msg.tool, msg.description, msg.args),
                        )
                        _uiState.update { it.copy(messages = it.messages + hitl) }
                    }
                    is WsMessage.Error -> {
                        // Backend reported an error — stop streaming so the user can retry
                        _uiState.update {
                            it.copy(isStreaming = false, streamingContent = "", isLoading = false)
                        }
                    }
                    else -> Unit
                }
            }
        }
        viewModelScope.launch {
            chatRepository.wsConnectionState.collect { s ->
                _uiState.update { it.copy(connectionState = s) }
                // Auto-reconnect on disconnect after 3 s
                if (s is ChatWebSocketClient.ConnectionState.Disconnected) {
                    // Also reset isStreaming — the backend cannot finish a response
                    // through a closed socket, so leaving it true blocks the input.
                    _uiState.update {
                        it.copy(isStreaming = false, isLoading = false, streamingContent = "")
                    }
                    _streamingWatchdog?.cancel()
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
        _startStreamingWatchdog()
        viewModelScope.launch {
            chatRepository.sendMessage(text)
            _uiState.update { it.copy(isLoading = false) }
        }
    }

    fun resolveHitl(actionId: String, decision: String) {
        chatRepository.sendHitlResponse(actionId, decision)
        _uiState.update { s -> s.copy(messages = s.messages.filter { it.id != "hitl_$actionId" }) }
    }

    /** Manually cancel an ongoing streaming response. */
    fun cancelStreaming() {
        _streamingWatchdog?.cancel()
        _uiState.update {
            it.copy(isStreaming = false, streamingContent = "", isLoading = false)
        }
    }

    /** Start a new empty conversation (keeps old ones in history). */
    fun startNewConversation() {
        _streamingWatchdog?.cancel()
        _uiState.update {
            it.copy(
                messages = emptyList(),
                currentConversationId = null,
                streamingContent = "",
                isStreaming = false,
                isLoading = false,
                inputText = "",
            )
        }
        chatRepository.resetCurrentConversation()
    }

    /** Switch to an existing conversation and load its messages. */
    fun switchConversation(conversationId: String) {
        _streamingWatchdog?.cancel()
        _uiState.update {
            it.copy(
                currentConversationId = conversationId,
                streamingContent = "",
                isStreaming = false,
                isLoading = false,
            )
        }
        chatRepository.switchConversation(conversationId)
    }

    /** Fetch conversation list from the backend (used by the drawer). */
    suspend fun loadConversations(): List<com.ely.agent.data.repository.ConversationSummary> {
        return chatRepository.listConversations(limit = 50)
    }

    private fun _startStreamingWatchdog() {
        _streamingWatchdog?.cancel()
        _streamingWatchdog = viewModelScope.launch {
            delay(90_000) // 90 s without any event — consider the stream dead
            _uiState.update {
                if (it.isStreaming) {
                    it.copy(
                        isStreaming = false,
                        streamingContent = if (it.streamingContent.isBlank()) "" else it.streamingContent + "\n(réponse interrompue)",
                        isLoading = false,
                    )
                } else it
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        _streamingWatchdog?.cancel()
        chatRepository.disconnect()
    }
}
