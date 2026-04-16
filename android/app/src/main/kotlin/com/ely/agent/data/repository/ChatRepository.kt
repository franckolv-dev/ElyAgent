// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/repository/ChatRepository.kt
// @brief      Chat repository interface
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

package com.ely.agent.data.repository

import com.ely.agent.core.model.Message
import com.ely.agent.data.remote.websocket.ChatWebSocketClient
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

interface ChatRepository {
    val wsConnectionState: StateFlow<ChatWebSocketClient.ConnectionState>
    fun observeMessages(): Flow<List<Message>>
    fun connect()
    suspend fun sendMessage(text: String)
    fun sendHitlResponse(actionId: String, decision: String)
    fun disconnect()
}
