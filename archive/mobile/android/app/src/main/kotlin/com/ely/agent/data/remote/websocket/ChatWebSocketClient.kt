// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/websocket/ChatWebSocketClient.kt
// @brief      Chat WebSocket client
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.remote.websocket

import androidx.datastore.core.DataStore
import com.ely.agent.UserPreferences
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.min

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

    // Background scope for reconnection attempts
    private val _scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var _reconnectJob: Job? = null
    private var _reconnectAttempts = 0

    // Set to true when the user explicitly disconnects — prevents auto-reconnect
    @Volatile private var _userDisconnected = false

    sealed class ConnectionState {
        object Connecting : ConnectionState()
        object Connected : ConnectionState()
        data class Disconnected(val reason: String = "") : ConnectionState()
    }

    fun connect() {
        _userDisconnected = false
        _reconnectJob?.cancel()
        _doConnect()
    }

    private fun _doConnect() {
        val prefs = runBlocking { dataStore.data.first() }
        val serverUrl = prefs.serverUrl.ifBlank { "http://10.0.2.2:8000" }
        val token = prefs.accessToken
        // Backend expects the JWT as the FIRST JSON message after accept() — not as
        // a URL query param (avoids token leaking in server logs / proxy logs).
        val wsUrl = serverUrl
            .replace("http://", "ws://")
            .replace("https://", "wss://")
            .trimEnd('/') + "/ws/chat"

        _connectionState.value = ConnectionState.Connecting
        val request = Request.Builder().url(wsUrl).build()
        webSocket = okHttpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                ws.send(org.json.JSONObject().put("token", token).toString())
                _connectionState.value = ConnectionState.Connected
                _reconnectAttempts = 0  // reset backoff on successful connect
            }
            override fun onMessage(ws: WebSocket, text: String) {
                _messages.tryEmit(WsMessageAdapter.parse(text))
            }
            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                _connectionState.value = ConnectionState.Disconnected(t.message ?: "Connection failed")
                _scheduleReconnect()
            }
            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                _connectionState.value = ConnectionState.Disconnected(reason)
                _scheduleReconnect()
            }
        })
    }

    /**
     * Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s… capped at 30 s).
     * Skipped when the user explicitly disconnected.
     */
    private fun _scheduleReconnect() {
        if (_userDisconnected) return
        _reconnectJob?.cancel()
        _reconnectJob = _scope.launch {
            val delayMs = min(30_000L, 1_000L * (1L shl _reconnectAttempts.coerceAtMost(5)))
            _reconnectAttempts++
            delay(delayMs)
            if (!_userDisconnected && _connectionState.value !is ConnectionState.Connected) {
                _doConnect()
            }
        }
    }

    fun send(text: String, conversationId: String? = null) {
        val pairs = buildList {
            add("type" to "message")
            add("content" to text)
            if (!conversationId.isNullOrBlank()) add("conversation_id" to conversationId)
        }
        val json = org.json.JSONObject()
        for ((k, v) in pairs) json.put(k, v)
        webSocket?.send(json.toString())
    }

    fun sendHitlResponse(actionId: String, decision: String) {
        webSocket?.send(
            WsMessageAdapter.toJson("hitl_response", "action_id" to actionId, "decision" to decision)
        )
    }

    /**
     * Tell the backend to stop the current agent turn.
     * The backend watches for "stop" messages inside its tool loop and
     * aborts generation + flushes a "stopped" response back.
     */
    fun sendStop() {
        webSocket?.send(org.json.JSONObject().put("type", "stop").toString())
    }

    /** Send a WebSocket ping to keep the connection alive (heartbeat). */
    fun sendPing() {
        try {
            webSocket?.send(org.json.JSONObject().put("type", "ping").toString())
        } catch (_: Exception) {
            // Ignore — if WS is broken, onFailure will trigger reconnect
        }
    }

    fun disconnect() {
        _userDisconnected = true
        _reconnectJob?.cancel()
        webSocket?.close(1000, "User disconnected")
        webSocket = null
        _connectionState.value = ConnectionState.Disconnected()
    }
}
