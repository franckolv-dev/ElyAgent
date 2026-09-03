// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Models/Conversation.swift
// @brief      Conversation model — thread metadata and message list
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

import Foundation

struct Conversation: Codable, Identifiable, Sendable, Hashable {
    let id: String
    let title: String
    let createdAt: Date
    let updatedAt: Date
    let messageCount: Int

    enum CodingKeys: String, CodingKey {
        case id, title
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case messageCount = "message_count"
    }

    init(id: String, title: String, createdAt: Date, updatedAt: Date, messageCount: Int = 0) {
        self.id = id
        self.title = title
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.messageCount = messageCount
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        title = try container.decode(String.self, forKey: .title)
        messageCount = try container.decodeIfPresent(Int.self, forKey: .messageCount) ?? 0

        // Support both ISO 8601 string and Unix timestamp
        if let timestamp = try? container.decode(Double.self, forKey: .createdAt) {
            createdAt = Date(timeIntervalSince1970: timestamp)
        } else {
            let str = try container.decode(String.self, forKey: .createdAt)
            createdAt = ISO8601DateFormatter().date(from: str) ?? Date()
        }

        if let timestamp = try? container.decode(Double.self, forKey: .updatedAt) {
            updatedAt = Date(timeIntervalSince1970: timestamp)
        } else {
            let str = try container.decode(String.self, forKey: .updatedAt)
            updatedAt = ISO8601DateFormatter().date(from: str) ?? Date()
        }
    }
}
