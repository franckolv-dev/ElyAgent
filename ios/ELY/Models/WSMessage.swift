// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Models/WSMessage.swift
// @brief      WebSocket message model — typed envelopes for agent protocol
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

import Foundation

/// Incoming WebSocket message types from the ELY backend
enum WSMessage: Sendable {
    case start(conversationId: String?)
    case token(content: String)
    case message(id: String, content: String, conversationId: String?)
    case error(message: String)
    case toolStart(tool: String)
    case toolEnd(tool: String)
    case hitlPending(actionId: String, tool: String, description: String, args: [String: String])
    case hitlResolved(actionId: String)
    case stopped
    case unknown(raw: String)

    /// Parse a raw JSON string into a WSMessage
    static func parse(_ raw: String) -> WSMessage {
        guard let data = raw.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else {
            return .unknown(raw: raw)
        }

        switch type {
        case "start":
            let convId = json["conversation_id"] as? String
            return .start(conversationId: convId)

        case "token":
            let content = json["content"] as? String ?? ""
            return .token(content: content)

        case "message":
            let id = json["id"] as? String ?? UUID().uuidString
            let content = json["content"] as? String ?? ""
            let convId = json["conversation_id"] as? String
            return .message(id: id, content: content, conversationId: convId)

        case "error":
            let message = json["message"] as? String ?? "Erreur inconnue"
            return .error(message: message)

        case "tool_start":
            let tool = json["tool"] as? String ?? ""
            return .toolStart(tool: tool)

        case "tool_end":
            let tool = json["tool"] as? String ?? ""
            return .toolEnd(tool: tool)

        case "hitl_pending":
            let actionId = json["action_id"] as? String ?? ""
            let tool = json["tool"] as? String ?? ""
            let description = json["description"] as? String ?? ""
            var args: [String: String] = [:]
            if let argsObj = json["args"] as? [String: Any] {
                for (key, value) in argsObj {
                    args[key] = "\(value)"
                }
            }
            return .hitlPending(actionId: actionId, tool: tool, description: description, args: args)

        case "hitl_resolved":
            let actionId = json["action_id"] as? String ?? ""
            return .hitlResolved(actionId: actionId)

        case "stopped":
            return .stopped

        default:
            return .unknown(raw: raw)
        }
    }

    /// Create an outgoing JSON message
    static func toJSON(type: String, pairs: [String: Any] = [:]) -> String {
        var dict: [String: Any] = ["type": type]
        for (key, value) in pairs {
            dict[key] = value
        }
        guard let data = try? JSONSerialization.data(withJSONObject: dict),
              let str = String(data: data, encoding: .utf8) else {
            return "{\"type\":\"\(type)\"}"
        }
        return str
    }
}
