// -----------------------------------------------------------------------------
// Copyright (c) 2024 Franck OLLIVIER
// Tous droits réservés.
//
// Ce logiciel est mis à disposition sous les termes de la licence
// PolyForm Strict License 1.0.0.
//
// RÉSUMÉ DES CONDITIONS :
// - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
// - INTERDIT : Toute utilisation commerciale sans accord préalable.
// - INTERDIT : Redistribution de versions modifiées de ce code.
//
// Pour consulter le texte intégral de la licence, veuillez vous référer au
// fichier LICENSE à la racine du projet ou visiter :
// https://polyformproject.org/licenses/strict/1.0.0/
// -----------------------------------------------------------------------------

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
