// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Views/VoiceModeView.swift
// @brief      Voice mode view — full-screen voice interaction overlay
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

import SwiftUI

struct VoiceModeView: View {
    @ObservedObject var chatVM: ChatViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var pulseScale: CGFloat = 1.0
    @State private var permissionsGranted = false

    private enum VoicePhase {
        case idle
        case listening
        case processing
        case speaking
    }

    private var phase: VoicePhase {
        if chatVM.ttsService.isPlaying {
            return .speaking
        } else if chatVM.isStreaming || chatVM.voiceRecorder.state == .processing {
            return .processing
        } else if chatVM.voiceRecorder.isRecording {
            return .listening
        }
        return .idle
    }

    private var phaseColor: Color {
        switch phase {
        case .idle: return ELYTheme.cyberCyan
        case .listening: return ELYTheme.cyberCyan
        case .processing: return ELYTheme.warningAmber
        case .speaking: return ELYTheme.successGreen
        }
    }

    private var phaseIcon: String {
        switch phase {
        case .idle: return "mic.fill"
        case .listening: return "waveform"
        case .processing: return "ellipsis"
        case .speaking: return "speaker.wave.3.fill"
        }
    }

    private var phaseLabel: String {
        switch phase {
        case .idle: return "Appuyez pour parler"
        case .listening: return "Ecoute en cours..."
        case .processing: return "Traitement..."
        case .speaking: return "Reponse en cours..."
        }
    }

    private var lastResponse: String? {
        chatVM.messages.last(where: { $0.role == .assistant })?.content
    }

    var body: some View {
        ZStack {
            // Background with blur
            ELYTheme.bgPrimary
                .ignoresSafeArea()
                .overlay(
                    ELYTheme.cyberCyan.opacity(0.03)
                        .ignoresSafeArea()
                )

            VStack(spacing: 32) {
                // Close button
                HStack {
                    Spacer()
                    Button {
                        chatVM.voiceRecorder.stopRecording()
                        chatVM.ttsService.stop()
                        dismiss()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 28))
                            .foregroundColor(ELYTheme.textMuted)
                    }
                    .padding(.trailing, 20)
                    .padding(.top, 12)
                }

                Spacer()

                // Central pulsing circle
                ZStack {
                    // Outer pulse rings
                    ForEach(0..<3, id: \.self) { index in
                        Circle()
                            .stroke(phaseColor.opacity(0.15), lineWidth: 2)
                            .frame(width: 180 + CGFloat(index) * 40,
                                   height: 180 + CGFloat(index) * 40)
                            .scaleEffect(phase != .idle ? pulseScale : 1.0)
                            .opacity(phase != .idle ? Double(3 - index) / 4.0 : 0.3)
                    }

                    // Main circle
                    Circle()
                        .fill(
                            RadialGradient(
                                gradient: Gradient(colors: [
                                    phaseColor.opacity(0.3),
                                    phaseColor.opacity(0.1)
                                ]),
                                center: .center,
                                startRadius: 20,
                                endRadius: 80
                            )
                        )
                        .frame(width: 160, height: 160)
                        .overlay(
                            Circle()
                                .stroke(phaseColor.opacity(0.5), lineWidth: 2)
                        )
                        .scaleEffect(phase != .idle ? pulseScale * 0.95 + 0.05 : 1.0)

                    // Icon
                    Image(systemName: phaseIcon)
                        .font(.system(size: 48, weight: .medium))
                        .foregroundColor(phaseColor)
                }
                .onTapGesture {
                    Task { await handleTap() }
                }

                // Phase label
                Text(phaseLabel)
                    .font(.headline)
                    .foregroundColor(phaseColor)
                    .padding(.top, 8)

                // Transcript (real-time)
                if chatVM.voiceRecorder.isRecording && !chatVM.voiceRecorder.transcript.isEmpty {
                    Text(chatVM.voiceRecorder.transcript)
                        .font(.body)
                        .foregroundColor(ELYTheme.textPrimary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                        .transition(.opacity)
                }

                // Streaming content
                if chatVM.isStreaming && !chatVM.streamingContent.isEmpty {
                    ScrollView {
                        Text(chatVM.streamingContent)
                            .font(.body)
                            .foregroundColor(ELYTheme.textSecondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 32)
                    }
                    .frame(maxHeight: 120)
                    .transition(.opacity)
                }

                Spacer()

                // Last response preview
                if let response = lastResponse {
                    VStack(spacing: 4) {
                        Text("Derniere reponse")
                            .font(.caption)
                            .foregroundColor(ELYTheme.textMuted)

                        Text(response)
                            .font(.callout)
                            .foregroundColor(ELYTheme.textSecondary)
                            .lineLimit(3)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 32)
                    }
                    .padding(.bottom, 32)
                }
            }
        }
        .onAppear {
            startPulseAnimation()
        }
        .onChange(of: phase) { _, _ in
            startPulseAnimation()
        }
        .animation(.easeInOut(duration: 0.3), value: phase)
    }

    // MARK: - Actions

    private func handleTap() async {
        switch phase {
        case .idle:
            if !permissionsGranted {
                permissionsGranted = await chatVM.voiceRecorder.requestPermissions()
                guard permissionsGranted else { return }
            }
            chatVM.voiceRecorder.startRecording()
        case .listening:
            chatVM.voiceRecorder.stopRecording()
        case .processing:
            break
        case .speaking:
            chatVM.ttsService.stop()
        }
    }

    // MARK: - Animation

    private func startPulseAnimation() {
        pulseScale = 1.0
        withAnimation(
            .easeInOut(duration: 1.2)
            .repeatForever(autoreverses: true)
        ) {
            pulseScale = 1.15
        }
    }
}

#Preview {
    VoiceModeView(chatVM: ChatViewModel())
}
