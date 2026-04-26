// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Models/User.swift
// @brief      User model — profile, credentials and preferences
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
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

struct User: Codable, Identifiable, Sendable {
    let id: String
    let username: String
    let isAdmin: Bool

    enum CodingKeys: String, CodingKey {
        case id, username
        case isAdmin = "is_admin"
    }
}

struct LoginResponse: Codable, Sendable {
    let accessToken: String
    let refreshToken: String
    let user: User

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case user
    }
}

struct RefreshResponse: Codable, Sendable {
    let accessToken: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
    }
}
