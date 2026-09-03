// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Services/TTSService.swift
// @brief      Text-to-speech service — audio synthesis and playback
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

import Foundation
import AVFoundation

// MARK: - TTS State

enum TTSState: Sendable {
    case idle
    case loading
    case playing
}

// MARK: - TTSService

@MainActor
final class TTSService: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published private(set) var state: TTSState = .idle

    private var audioPlayer: AVAudioPlayer?
    private var onFinished: (() -> Void)?

    override init() {
        super.init()
        configureAudioSession()
    }

    // MARK: - Public API

    func speak(text: String, serverURL: String, token: String, onFinished: (() -> Void)? = nil) {
        stop()
        self.onFinished = onFinished
        state = .loading

        Task {
            do {
                let api = APIService(serverURL: serverURL, token: token)
                let audioData = try await api.fetchTTSAudio(text: text)
                try playAudio(data: audioData)
            } catch {
                print("[TTS] Erreur : \(error.localizedDescription)")
                state = .idle
                self.onFinished?()
            }
        }
    }

    func stop() {
        audioPlayer?.stop()
        audioPlayer = nil
        state = .idle
    }

    var isPlaying: Bool {
        state == .playing
    }

    // MARK: - AVAudioPlayerDelegate

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            state = .idle
            onFinished?()
        }
    }

    // MARK: - Private

    private func configureAudioSession() {
        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.playback, mode: .default)
            try audioSession.setActive(true)
        } catch {
            print("[TTS] Erreur configuration audio : \(error.localizedDescription)")
        }
    }

    private func playAudio(data: Data) throws {
        audioPlayer = try AVAudioPlayer(data: data)
        audioPlayer?.delegate = self
        audioPlayer?.prepareToPlay()
        audioPlayer?.play()
        state = .playing
    }
}
