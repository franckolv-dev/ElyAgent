// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Views/SettingsView.swift
// @brief      Settings view — user preferences and app configuration
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var authVM: AuthViewModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var settingsVM = SettingsViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                ELYTheme.bgPrimary
                    .ignoresSafeArea()

                List {
                    // Account section
                    Section {
                        // Server URL
                        HStack {
                            Label("Serveur", systemImage: "server.rack")
                                .foregroundColor(ELYTheme.textSecondary)
                            Spacer()
                            Text(settingsVM.serverURL)
                                .font(.caption)
                                .foregroundColor(ELYTheme.textMuted)
                                .lineLimit(1)
                        }
                        .listRowBackground(ELYTheme.bgSecondary)

                        // Username
                        HStack {
                            Label("Utilisateur", systemImage: "person")
                                .foregroundColor(ELYTheme.textSecondary)
                            Spacer()
                            Text(settingsVM.username)
                                .font(.caption)
                                .foregroundColor(ELYTheme.textMuted)
                        }
                        .listRowBackground(ELYTheme.bgSecondary)
                    } header: {
                        Text("Compte")
                            .foregroundColor(ELYTheme.cyberCyan)
                    }

                    // Voice section
                    Section {
                        // Voice selection
                        Picker(selection: $settingsVM.selectedVoice) {
                            ForEach(settingsVM.availableVoices, id: \.self) { voice in
                                Text(voice.capitalized)
                                    .tag(voice)
                            }
                        } label: {
                            Label("Voix", systemImage: "speaker.wave.3")
                                .foregroundColor(ELYTheme.textSecondary)
                        }
                        .listRowBackground(ELYTheme.bgSecondary)
                        .tint(ELYTheme.cyberCyan)

                        // Auto-play TTS
                        Toggle(isOn: $settingsVM.autoPlayTTS) {
                            Label("Lecture auto", systemImage: "play.circle")
                                .foregroundColor(ELYTheme.textSecondary)
                        }
                        .listRowBackground(ELYTheme.bgSecondary)
                        .tint(ELYTheme.cyberCyan)

                        // Haptic feedback
                        Toggle(isOn: $settingsVM.hapticFeedback) {
                            Label("Retour haptique", systemImage: "hand.tap")
                                .foregroundColor(ELYTheme.textSecondary)
                        }
                        .listRowBackground(ELYTheme.bgSecondary)
                        .tint(ELYTheme.cyberCyan)
                    } header: {
                        Text("Voix et Audio")
                            .foregroundColor(ELYTheme.cyberCyan)
                    }

                    // App info section
                    Section {
                        HStack {
                            Label("Version", systemImage: "info.circle")
                                .foregroundColor(ELYTheme.textSecondary)
                            Spacer()
                            Text(settingsVM.appVersion)
                                .font(.caption)
                                .foregroundColor(ELYTheme.textMuted)
                        }
                        .listRowBackground(ELYTheme.bgSecondary)
                    } header: {
                        Text("Application")
                            .foregroundColor(ELYTheme.cyberCyan)
                    }

                    // Logout section
                    Section {
                        Button {
                            authVM.logout()
                            dismiss()
                        } label: {
                            HStack {
                                Spacer()
                                Label("Deconnexion", systemImage: "rectangle.portrait.and.arrow.right")
                                    .foregroundColor(ELYTheme.dangerRed)
                                    .fontWeight(.medium)
                                Spacer()
                            }
                        }
                        .listRowBackground(ELYTheme.dangerRed.opacity(0.1))
                    }
                }
                .listStyle(.insetGrouped)
                .scrollContentBackground(.hidden)
            }
            .navigationTitle("Parametres")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(ELYTheme.bgSecondary, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fermer") {
                        dismiss()
                    }
                    .foregroundColor(ELYTheme.cyberCyan)
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .onAppear {
            settingsVM.configure(authService: authVM.authService)
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(AuthViewModel())
}
