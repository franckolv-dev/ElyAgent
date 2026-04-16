// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/websocket/ChatWebSocketClient.kt
// @brief      Chat WebSocket client
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

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
                // Send token handshake immediately so the backend can authenticate
                // (it times out after 10 s if no handshake arrives). The backend
                // only reads the "token" field — no "type" field is needed.
                ws.send(org.json.JSONObject().put("token", token).toString())
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
        webSocket?.send(WsMessageAdapter.toJson("message", "content" to text))
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
