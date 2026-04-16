// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/websocket/WsMessageAdapter.kt
// @brief      WebSocket message type adapter
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

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.json.JSONObject

object WsMessageAdapter {
    fun parse(raw: String): WsMessage = try {
        val json = JSONObject(raw)
        when (json.optString("type")) {
            "start" -> WsMessage.Start(json.optString("conversation_id").ifBlank { null })
            "token" -> WsMessage.Token(json.optString("content"))
            "message" -> WsMessage.MessageComplete(
                id = json.optString("id", java.util.UUID.randomUUID().toString()),
                content = json.optString("content"),
                conversationId = json.optString("conversation_id").ifBlank { null }
            )
            "hitl_pending" -> WsMessage.HitlPending(
                actionId = json.optString("action_id"),
                tool = json.optString("tool"),
                description = json.optString("description"),
                args = buildMap {
                    json.optJSONObject("args")?.let { argsObj ->
                        argsObj.keys().forEach { key -> put(key, argsObj.optString(key)) }
                    }
                }
            )
            "error" -> WsMessage.Error(json.optString("message"))
            else -> WsMessage.Unknown(raw)
        }
    } catch (e: Exception) {
        WsMessage.Unknown(raw)
    }

    fun toJson(type: String, vararg pairs: Pair<String, Any>): String {
        val json = JSONObject()
        json.put("type", type)
        pairs.forEach { (k, v) -> json.put(k, v) }
        return json.toString()
    }
}
