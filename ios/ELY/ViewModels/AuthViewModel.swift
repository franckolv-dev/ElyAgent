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
