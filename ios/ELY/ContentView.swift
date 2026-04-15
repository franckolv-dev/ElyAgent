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

import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var authVM: AuthViewModel

    var body: some View {
        Group {
            if authVM.isAuthenticated {
                NavigationStack {
                    ChatView()
                        .environmentObject(authVM)
                }
            } else {
                LoginView()
                    .environmentObject(authVM)
            }
        }
        .animation(.easeInOut(duration: 0.3), value: authVM.isAuthenticated)
    }
}

#Preview {
    ContentView()
        .environmentObject(AuthViewModel())
}
