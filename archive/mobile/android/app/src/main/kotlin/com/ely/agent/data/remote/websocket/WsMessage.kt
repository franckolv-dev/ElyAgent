// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/websocket/WsMessage.kt
// @brief      WebSocket message types
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

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
