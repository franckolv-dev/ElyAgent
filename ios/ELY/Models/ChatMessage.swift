// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Models/ChatMessage.swift
// @brief      Chat message model — content, role, timestamp
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

enum MessageRole: String, Codable, Sendable {
    case user
    case assistant
    case system
    case hitlPending = "hitl_pending"
}

struct HitlRequest: Identifiable, Sendable {
    let id: String
    let actionId: String
    let tool: String
    let description: String
    let args: [String: String]

    init(actionId: String, tool: String, description: String, args: [String: String] = [:]) {
        self.id = actionId
        self.actionId = actionId
        self.tool = tool
        self.description = description
        self.args = args
    }
}

struct ChatMessage: Identifiable, Sendable {
    let id: String
    let conversationId: String
    let role: MessageRole
    let content: String
    var streamingContent: String
    var isStreaming: Bool
    let timestamp: Date
    var hitlRequest: HitlRequest?
    var toolName: String?
    var isToolActive: Bool

    init(
        id: String = UUID().uuidString,
        conversationId: String = "",
        role: MessageRole,
        content: String,
        streamingContent: String = "",
        isStreaming: Bool = false,
        timestamp: Date = Date(),
        hitlRequest: HitlRequest? = nil,
        toolName: String? = nil,
        isToolActive: Bool = false
    ) {
        self.id = id
        self.conversationId = conversationId
        self.role = role
        self.content = content
        self.streamingContent = streamingContent
        self.isStreaming = isStreaming
        self.timestamp = timestamp
        self.hitlRequest = hitlRequest
        self.toolName = toolName
        self.isToolActive = isToolActive
    }
}
