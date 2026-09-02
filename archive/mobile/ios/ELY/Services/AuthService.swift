// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Services/AuthService.swift
// @brief      Authentication service — login, token storage, session management
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
import Security

// MARK: - Keychain Helper

private enum KeychainKey {
    static let accessToken = "com.ely.agent.accessToken"
    static let refreshToken = "com.ely.agent.refreshToken"
    static let userId = "com.ely.agent.userId"
    static let username = "com.ely.agent.username"
}

private enum Keychain {
    static func save(key: String, value: String) {
        guard let data = value.data(using: .utf8) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock
        ]
        // Delete existing
        SecItemDelete(query as CFDictionary)
        // Add new
        var addQuery = query
        addQuery[kSecValueData as String] = data
        SecItemAdd(addQuery as CFDictionary, nil)
    }

    static func load(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key
        ]
        SecItemDelete(query as CFDictionary)
    }

    static func deleteAll() {
        delete(key: KeychainKey.accessToken)
        delete(key: KeychainKey.refreshToken)
        delete(key: KeychainKey.userId)
        delete(key: KeychainKey.username)
    }
}

// MARK: - UserDefaults keys

private enum DefaultsKey {
    static let serverURL = "com.ely.agent.serverURL"
    static let isAdmin = "com.ely.agent.isAdmin"
}

// MARK: - Auth Errors

enum AuthError: LocalizedError, Sendable {
    case invalidURL
    case invalidCredentials
    case networkError(String)
    case serverError(Int, String)
    case tokenExpired
    case noToken

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "URL du serveur invalide"
        case .invalidCredentials:
            return "Identifiants incorrects"
        case .networkError(let msg):
            return "Erreur réseau : \(msg)"
        case .serverError(let code, let msg):
            return "Erreur serveur (\(code)) : \(msg)"
        case .tokenExpired:
            return "Session expirée, veuillez vous reconnecter"
        case .noToken:
            return "Aucun token d'authentification"
        }
    }
}

// MARK: - AuthService

@MainActor
final class AuthService: ObservableObject {
    @Published private(set) var isAuthenticated = false
    @Published private(set) var currentUser: User?

    var serverURL: String {
        get { UserDefaults.standard.string(forKey: DefaultsKey.serverURL) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: DefaultsKey.serverURL) }
    }

    var accessToken: String? {
        Keychain.load(key: KeychainKey.accessToken)
    }

    private var refreshToken: String? {
        Keychain.load(key: KeychainKey.refreshToken)
    }

    init() {
        restoreSession()
    }

    // MARK: - Public API

    func login(serverURL: String, username: String, password: String) async throws -> User {
        let cleanURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: "\(cleanURL)/auth/login") else {
            throw AuthError.invalidURL
        }

        self.serverURL = cleanURL

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 15

        let body: [String: String] = ["username": username, "password": password]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.networkError("Réponse invalide")
        }

        switch httpResponse.statusCode {
        case 200:
            let loginResponse = try JSONDecoder().decode(LoginResponse.self, from: data)
            saveTokens(access: loginResponse.accessToken, refresh: loginResponse.refreshToken)
            saveUserInfo(loginResponse.user)
            isAuthenticated = true
            currentUser = loginResponse.user
            return loginResponse.user

        case 401:
            throw AuthError.invalidCredentials

        default:
            let errorMsg = String(data: data, encoding: .utf8) ?? "Erreur inconnue"
            throw AuthError.serverError(httpResponse.statusCode, errorMsg)
        }
    }

    func refreshAccessToken() async throws {
        guard let refreshTok = refreshToken else {
            throw AuthError.noToken
        }

        let cleanURL = serverURL
        guard let url = URL(string: "\(cleanURL)/auth/refresh") else {
            throw AuthError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(refreshTok)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 10

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.networkError("Réponse invalide")
        }

        if httpResponse.statusCode == 200 {
            let refreshResponse = try JSONDecoder().decode(RefreshResponse.self, from: data)
            Keychain.save(key: KeychainKey.accessToken, value: refreshResponse.accessToken)
        } else {
            logout()
            throw AuthError.tokenExpired
        }
    }

    func logout() {
        Keychain.deleteAll()
        UserDefaults.standard.removeObject(forKey: DefaultsKey.isAdmin)
        isAuthenticated = false
        currentUser = nil
    }

    // MARK: - Private

    private func saveTokens(access: String, refresh: String) {
        Keychain.save(key: KeychainKey.accessToken, value: access)
        Keychain.save(key: KeychainKey.refreshToken, value: refresh)
    }

    private func saveUserInfo(_ user: User) {
        Keychain.save(key: KeychainKey.userId, value: user.id)
        Keychain.save(key: KeychainKey.username, value: user.username)
        UserDefaults.standard.set(user.isAdmin, forKey: DefaultsKey.isAdmin)
    }

    private func restoreSession() {
        guard let token = Keychain.load(key: KeychainKey.accessToken),
              !token.isEmpty,
              let userId = Keychain.load(key: KeychainKey.userId),
              let username = Keychain.load(key: KeychainKey.username) else {
            isAuthenticated = false
            return
        }
        let isAdmin = UserDefaults.standard.bool(forKey: DefaultsKey.isAdmin)
        currentUser = User(id: userId, username: username, isAdmin: isAdmin)
        isAuthenticated = true
    }
}
