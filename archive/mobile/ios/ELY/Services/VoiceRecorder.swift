// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Services/VoiceRecorder.swift
// @brief      Voice recording and audio capture
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

import Foundation
import Speech
import AVFoundation

// MARK: - Voice Recorder State

enum VoiceRecorderState: Sendable {
    case idle
    case requesting
    case recording
    case processing
    case error(String)
}

// MARK: - VoiceRecorder

@MainActor
final class VoiceRecorder: ObservableObject {
    @Published private(set) var state: VoiceRecorderState = .idle
    @Published private(set) var transcript: String = ""
    @Published private(set) var isRecording: Bool = false

    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var audioEngine = AVAudioEngine()

    /// Fallback: AVAudioRecorder for server-side transcription
    private var audioRecorder: AVAudioRecorder?
    private var recordingURL: URL?

    /// Silence detection
    private var silenceTimer: Timer?
    private var lastTranscriptUpdate: Date = Date()
    private let silenceTimeout: TimeInterval = 2.0

    /// Wake word detection
    var onWakeWordDetected: (() -> Void)?
    private let wakeWord = "éli"

    /// Callback when final transcript is ready
    var onTranscriptReady: ((String) -> Void)?

    /// Whether to use on-device Speech recognition (true) or server fallback (false)
    private(set) var useSpeechFramework: Bool = true

    init() {
        speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "fr-FR"))
    }

    // MARK: - Public API

    func requestPermissions() async -> Bool {
        state = .requesting

        // Microphone permission
        let micGranted = await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }

        guard micGranted else {
            state = .error("Accès au microphone refusé")
            return false
        }

        // Speech recognition permission
        let speechGranted = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }

        if !speechGranted {
            // Fall back to server transcription
            useSpeechFramework = false
            print("[Voice] Speech non autorisé, utilisation du serveur pour la transcription")
        }

        state = .idle
        return true
    }

    func startRecording() {
        guard state == .idle else { return }

        transcript = ""
        isRecording = true

        if useSpeechFramework {
            startSpeechRecognition()
        } else {
            startAudioRecording()
        }
    }

    func stopRecording() {
        isRecording = false
        silenceTimer?.invalidate()
        silenceTimer = nil

        if useSpeechFramework {
            stopSpeechRecognition()
        } else {
            stopAudioRecording()
        }
    }

    /// Get the recorded audio file URL (for server fallback)
    func getRecordingURL() -> URL? {
        recordingURL
    }

    /// Get recorded audio data (for server fallback)
    func getRecordingData() -> Data? {
        guard let url = recordingURL else { return nil }
        return try? Data(contentsOf: url)
    }

    // MARK: - Speech Framework Recognition

    private func startSpeechRecognition() {
        guard let recognizer = speechRecognizer, recognizer.isAvailable else {
            state = .error("Reconnaissance vocale non disponible")
            isRecording = false
            return
        }

        state = .recording

        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            state = .error("Erreur configuration audio : \(error.localizedDescription)")
            isRecording = false
            return
        }

        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let request = recognitionRequest else {
            state = .error("Impossible de créer la requête")
            isRecording = false
            return
        }

        request.shouldReportPartialResults = true
        request.addsPunctuation = true

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, _ in
            self?.recognitionRequest?.append(buffer)
        }

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }

                if let result {
                    self.transcript = result.bestTranscription.formattedString
                    self.lastTranscriptUpdate = Date()
                    self.resetSilenceTimer()

                    // Wake word detection
                    if self.transcript.lowercased().contains(self.wakeWord) {
                        self.onWakeWordDetected?()
                    }

                    if result.isFinal {
                        self.finishRecording()
                    }
                }

                if let error {
                    print("[Voice] Erreur reconnaissance : \(error.localizedDescription)")
                    if self.isRecording {
                        self.finishRecording()
                    }
                }
            }
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            state = .error("Impossible de démarrer le moteur audio")
            isRecording = false
        }
    }

    private func stopSpeechRecognition() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil
    }

    // MARK: - Audio Recording Fallback

    private func startAudioRecording() {
        state = .recording

        let filename = "voice_\(Int(Date().timeIntervalSince1970)).m4a"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        recordingURL = url

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 16000,
            AVNumberOfChannelsKey: 1,
            AVEncoderBitRateKey: 64000,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue
        ]

        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.record, mode: .measurement)
            try audioSession.setActive(true)

            audioRecorder = try AVAudioRecorder(url: url, settings: settings)
            audioRecorder?.record()
        } catch {
            state = .error("Erreur enregistrement : \(error.localizedDescription)")
            isRecording = false
        }
    }

    private func stopAudioRecording() {
        audioRecorder?.stop()
        audioRecorder = nil
        state = .processing
        // The caller should upload the file to /api/transcribe
        finishRecording()
    }

    // MARK: - Silence Detection

    private func resetSilenceTimer() {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: silenceTimeout, repeats: false) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isRecording else { return }
                self.stopRecording()
            }
        }
    }

    // MARK: - Finalization

    private func finishRecording() {
        state = .idle
        isRecording = false
        let finalText = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        if !finalText.isEmpty {
            onTranscriptReady?(finalText)
        }
    }
}
