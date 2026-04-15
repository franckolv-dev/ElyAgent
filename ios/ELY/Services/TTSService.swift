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
