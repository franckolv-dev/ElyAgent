// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/websocket/WsMessage.kt
// @brief      WebSocket message types
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
