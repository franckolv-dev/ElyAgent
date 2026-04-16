// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/ViewModels/AuthViewModel.swift
// @brief      Authentication view model — login state and session handling
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

@MainActor
final class AuthViewModel: ObservableObject {
    @Published var serverURL: String = ""
    @Published var username: String = ""
    @Published var password: String = ""
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?

    let authService = AuthService()

    var isAuthenticated: Bool {
        authService.isAuthenticated
    }

    var currentUser: User? {
        authService.currentUser
    }

    init() {
        // Restore saved server URL
        let savedURL = authService.serverURL
        if !savedURL.isEmpty {
            serverURL = savedURL
        } else {
            serverURL = "https://"
        }
    }

    // MARK: - Login

    func login() async {
        guard !serverURL.isEmpty, !username.isEmpty, !password.isEmpty else {
            errorMessage = "Veuillez remplir tous les champs"
            return
        }

        isLoading = true
        errorMessage = nil

        do {
            _ = try await authService.login(
                serverURL: serverURL,
                username: username,
                password: password
            )
            // Clear sensitive fields on success
            password = ""
            objectWillChange.send()
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    // MARK: - Logout

    func logout() {
        authService.logout()
        password = ""
        errorMessage = nil
        objectWillChange.send()
    }
}
