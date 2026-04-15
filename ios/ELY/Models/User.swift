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
