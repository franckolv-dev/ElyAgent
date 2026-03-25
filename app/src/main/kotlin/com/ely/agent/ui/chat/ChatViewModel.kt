package com.ely.agent.ui.chat

import androidx.datastore.core.DataStore
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ely.agent.UserPreferences  // généré par protobuf
import com.ely.agent.core.model.HitlRequest
import com.ely.agent.core.model.Message
import com.ely.agent.core.model.MessageRole
import com.ely.agent.data.remote.api.TranscribeApi
import com.ely.agent.data.remote.websocket.ChatWebSocketClient
import com.ely.agent.data.remote.websocket.WsMessage
import com.ely.agent.data.repository.ChatRepository
import com.ely.agent.service.VoiceRecorderManager
import com.ely.agent.ui.components.avatar.AvatarState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import javax.inject.Inject

data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val streamingContent: String = "",
    val isStreaming: Boolean = false,
    val inputText: String = "",
    val isLoading: Boolean = false,
    val isRecording: Boolean = false,
    val isTranscribing: Boolean = false,
    val connectionState: ChatWebSocketClient.ConnectionState = ChatWebSocketClient.ConnectionState.Disconnected(),
    val avatarState: AvatarState = AvatarState.IDLE,
    val showAvatar: Boolean = true
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val wsClient: ChatWebSocketClient,
    private val dataStore: DataStore<UserPreferences>,
    private val voiceRecorderManager: VoiceRecorderManager,
    private val transcribeApi: TranscribeApi
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

        // Lecture de la préférence showAvatar depuis DataStore
        // hide_avatar défaut proto = false → showAvatar = true par défaut
        viewModelScope.launch {
            dataStore.data.collect { prefs ->
                _uiState.update { it.copy(showAvatar = !prefs.hideAvatar) }
            }
        }

        // Mapping messages WebSocket → état avatar
        viewModelScope.launch {
            wsClient.messages.collect { msg ->
                when (msg) {
                    is WsMessage.Start -> _uiState.update {
                        it.copy(
                            isStreaming = true,
                            streamingContent = "",
                            avatarState = AvatarState.THINKING
                        )
                    }
                    is WsMessage.Token -> _uiState.update {
                        it.copy(
                            streamingContent = it.streamingContent + msg.content,
                            avatarState = AvatarState.SPEAKING
                        )
                    }
                    is WsMessage.MessageComplete -> _uiState.update {
                        it.copy(
                            isStreaming = false,
                            streamingContent = "",
                            avatarState = AvatarState.IDLE
                        )
                    }
                    is WsMessage.HitlPending -> {
                        val hitl = Message(
                            id = "hitl_${msg.actionId}",
                            conversationId = "",
                            role = MessageRole.HITL_PENDING,
                            content = msg.description,
                            hitlRequest = HitlRequest(msg.actionId, msg.tool, msg.description, msg.args)
                        )
                        _uiState.update {
                            it.copy(
                                messages = it.messages + hitl,
                                avatarState = AvatarState.ALERT
                            )
                        }
                    }
                    else -> Unit
                }
            }
        }

        viewModelScope.launch {
            chatRepository.wsConnectionState.collect { s ->
                _uiState.update { it.copy(connectionState = s) }
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
        _uiState.update { it.copy(inputText = "", isLoading = true, avatarState = AvatarState.THINKING) }
        viewModelScope.launch {
            chatRepository.sendMessage(text)
            _uiState.update { it.copy(isLoading = false) }
        }
    }

    fun resolveHitl(actionId: String, decision: String) {
        chatRepository.sendHitlResponse(actionId, decision)
        _uiState.update { s ->
            s.copy(
                messages = s.messages.filter { it.id != "hitl_$actionId" },
                avatarState = AvatarState.IDLE
            )
        }
    }

    /**
     * Bascule l'enregistrement vocal.
     * - 1er appel → démarre l'enregistrement, avatar = LISTENING
     * - 2e appel → arrête, transcrit via Whisper, envoie le texte reconnu
     */
    fun toggleVoiceRecording() {
        if (voiceRecorderManager.isRecording()) {
            // Arrêt de l'enregistrement et transcription
            val file = voiceRecorderManager.stopRecording()
            if (file == null) {
                _uiState.update { it.copy(isRecording = false, avatarState = AvatarState.IDLE) }
                return
            }
            _uiState.update { it.copy(isRecording = false, isTranscribing = true, avatarState = AvatarState.THINKING) }
            viewModelScope.launch {
                try {
                    val body = file.asRequestBody("audio/m4a".toMediaType())
                    val part = MultipartBody.Part.createFormData("file", file.name, body)
                    val response = transcribeApi.transcribe(part)
                    _uiState.update { it.copy(isTranscribing = false) }
                    if (response.text.isNotBlank()) {
                        _uiState.update { it.copy(inputText = response.text) }
                        sendMessage()
                    } else {
                        _uiState.update { it.copy(avatarState = AvatarState.IDLE) }
                    }
                } catch (_: Exception) {
                    _uiState.update { it.copy(isTranscribing = false, avatarState = AvatarState.IDLE) }
                } finally {
                    file.delete()
                }
            }
        } else {
            // Démarrage de l'enregistrement
            voiceRecorderManager.startRecording()
            _uiState.update { it.copy(isRecording = true, avatarState = AvatarState.LISTENING) }
        }
    }

    override fun onCleared() {
        super.onCleared()
        // Nettoyer l'enregistrement si l'écran est détruit pendant l'enregistrement
        if (voiceRecorderManager.isRecording()) {
            voiceRecorderManager.stopRecording()?.delete()
        }
        chatRepository.disconnect()
    }
}
