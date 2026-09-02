// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/ViewModels/SettingsViewModel.swift
// @brief      Settings view model — user preferences and configuration
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

@MainActor
final class SettingsViewModel: ObservableObject {
    // MARK: - Stored settings keys

    private enum SettingsKey {
        static let selectedVoice = "com.ely.settings.selectedVoice"
        static let autoPlayTTS = "com.ely.settings.autoPlayTTS"
        static let hapticFeedback = "com.ely.settings.hapticFeedback"
    }

    // MARK: - Published properties

    @Published var selectedVoice: String {
        didSet {
            UserDefaults.standard.set(selectedVoice, forKey: SettingsKey.selectedVoice)
        }
    }

    @Published var autoPlayTTS: Bool {
        didSet {
            UserDefaults.standard.set(autoPlayTTS, forKey: SettingsKey.autoPlayTTS)
        }
    }

    @Published var hapticFeedback: Bool {
        didSet {
            UserDefaults.standard.set(hapticFeedback, forKey: SettingsKey.hapticFeedback)
        }
    }

    // MARK: - Available voices

    let availableVoices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    // MARK: - Read-only info

    var serverURL: String {
        authService?.serverURL ?? ""
    }

    var username: String {
        authService?.currentUser?.username ?? ""
    }

    var appVersion: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(version) (\(build))"
    }

    private weak var authService: AuthService?

    // MARK: - Init

    init(authService: AuthService? = nil) {
        self.authService = authService
        self.selectedVoice = UserDefaults.standard.string(forKey: SettingsKey.selectedVoice) ?? "nova"
        self.autoPlayTTS = UserDefaults.standard.bool(forKey: SettingsKey.autoPlayTTS)
        self.hapticFeedback = UserDefaults.standard.object(forKey: SettingsKey.hapticFeedback) as? Bool ?? true
    }

    func configure(authService: AuthService) {
        self.authService = authService
    }
}
