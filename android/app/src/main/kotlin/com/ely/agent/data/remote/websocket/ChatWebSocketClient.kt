package com.ely.agent.data.remote.websocket

import androidx.datastore.core.DataStore
import com.ely.agent.UserPreferences
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatWebSocketClient @Inject constructor(
    private val okHttpClient: OkHttpClient,
    private val dataStore: DataStore<UserPreferences>
) {
    private val _messages = MutableSharedFlow<WsMessage>(extraBufferCapacity = 64)
    val messages: SharedFlow<WsMessage> = _messages.asSharedFlow()

    private val _connectionState = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected())
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private var webSocket: WebSocket? = null

    sealed class ConnectionState {
        object Connecting : ConnectionState()
        object Connected : ConnectionState()
        data class Disconnected(val reason: String = "") : ConnectionState()
    }

    fun connect() {
        val prefs = runBlocking { dataStore.data.first() }
        val serverUrl = prefs.serverUrl.ifBlank { "http://10.0.2.2:8000" }
        val token = prefs.accessToken
        val wsUrl = serverUrl
            .replace("http://", "ws://")
            .replace("https://", "wss://")
            .trimEnd('/') + "/ws?token=$token"

        _connectionState.value = ConnectionState.Connecting
        val request = Request.Builder().url(wsUrl).build()
        webSocket = okHttpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                _connectionState.value = ConnectionState.Connected
            }
            override fun onMessage(ws: WebSocket, text: String) {
                _messages.tryEmit(WsMessageAdapter.parse(text))
            }
            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                _connectionState.value = ConnectionState.Disconnected(t.message ?: "Connection failed")
            }
            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                _connectionState.value = ConnectionState.Disconnected(reason)
            }
        })
    }

    fun send(text: String) {
        webSocket?.send(WsMessageAdapter.toJson("message", "message" to text))
    }

    fun sendHitlResponse(actionId: String, decision: String) {
        webSocket?.send(
            WsMessageAdapter.toJson("hitl_response", "action_id" to actionId, "decision" to decision)
        )
    }

    fun disconnect() {
        webSocket?.close(1000, "User disconnected")
        webSocket = null
        _connectionState.value = ConnectionState.Disconnected()
    }
}
