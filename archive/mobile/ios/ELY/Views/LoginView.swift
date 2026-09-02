// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Views/LoginView.swift
// @brief      Login view — credential form and authentication flow
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

import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var authVM: AuthViewModel
    @FocusState private var focusedField: Field?

    private enum Field: Hashable {
        case serverURL, username, password
    }

    var body: some View {
        ZStack {
            // Background
            ELYTheme.bgPrimary
                .ignoresSafeArea()

            VStack(spacing: 32) {
                Spacer()

                // Logo / Title
                VStack(spacing: 8) {
                    Text("ELY")
                        .font(.system(size: 56, weight: .bold, design: .monospaced))
                        .foregroundColor(ELYTheme.cyberCyan)
                        .shadow(color: ELYTheme.cyberCyan.opacity(0.5), radius: 20, x: 0, y: 0)

                    Text("Agent Personnel Securise")
                        .font(.subheadline)
                        .foregroundColor(ELYTheme.textMuted)
                        .tracking(2)
                }

                // Form
                VStack(spacing: 16) {
                    // Server URL
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Serveur")
                            .font(.caption)
                            .foregroundColor(ELYTheme.textSecondary)

                        TextField("https://", text: $authVM.serverURL)
                            .textFieldStyle(.plain)
                            .padding(12)
                            .background(ELYTheme.bgSecondary)
                            .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall))
                            .overlay(
                                RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall)
                                    .stroke(
                                        focusedField == .serverURL ? ELYTheme.cyberCyan.opacity(0.5) : ELYTheme.borderDim,
                                        lineWidth: 1
                                    )
                            )
                            .foregroundColor(ELYTheme.textPrimary)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .keyboardType(.URL)
                            .focused($focusedField, equals: .serverURL)
                            .submitLabel(.next)
                            .onSubmit { focusedField = .username }
                    }

                    // Username
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Identifiant")
                            .font(.caption)
                            .foregroundColor(ELYTheme.textSecondary)

                        TextField("Nom d'utilisateur", text: $authVM.username)
                            .textFieldStyle(.plain)
                            .padding(12)
                            .background(ELYTheme.bgSecondary)
                            .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall))
                            .overlay(
                                RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall)
                                    .stroke(
                                        focusedField == .username ? ELYTheme.cyberCyan.opacity(0.5) : ELYTheme.borderDim,
                                        lineWidth: 1
                                    )
                            )
                            .foregroundColor(ELYTheme.textPrimary)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .focused($focusedField, equals: .username)
                            .submitLabel(.next)
                            .onSubmit { focusedField = .password }
                    }

                    // Password
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Mot de passe")
                            .font(.caption)
                            .foregroundColor(ELYTheme.textSecondary)

                        SecureField("Mot de passe", text: $authVM.password)
                            .textFieldStyle(.plain)
                            .padding(12)
                            .background(ELYTheme.bgSecondary)
                            .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall))
                            .overlay(
                                RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall)
                                    .stroke(
                                        focusedField == .password ? ELYTheme.cyberCyan.opacity(0.5) : ELYTheme.borderDim,
                                        lineWidth: 1
                                    )
                            )
                            .foregroundColor(ELYTheme.textPrimary)
                            .focused($focusedField, equals: .password)
                            .submitLabel(.go)
                            .onSubmit {
                                Task { await authVM.login() }
                            }
                    }
                }
                .padding(.horizontal, 32)

                // Error message
                if let error = authVM.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundColor(ELYTheme.dangerRed)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                }

                // Login button
                Button {
                    focusedField = nil
                    Task { await authVM.login() }
                } label: {
                    Group {
                        if authVM.isLoading {
                            ProgressView()
                                .tint(ELYTheme.bgPrimary)
                        } else {
                            Text("Connexion")
                                .font(.headline)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .frame(height: 48)
                    .foregroundColor(ELYTheme.bgPrimary)
                    .background(
                        authVM.isLoading
                            ? ELYTheme.cyberCyanDim
                            : ELYTheme.cyberCyan
                    )
                    .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusMedium))
                }
                .disabled(authVM.isLoading)
                .padding(.horizontal, 32)

                Spacer()
                Spacer()
            }
        }
    }
}

#Preview {
    LoginView()
        .environmentObject(AuthViewModel())
}
