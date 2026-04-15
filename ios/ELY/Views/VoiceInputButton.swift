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

struct VoiceInputButton: View {
    @ObservedObject var voiceRecorder: VoiceRecorder
    @State private var pulseScale: CGFloat = 1.0
    @State private var permissionsGranted: Bool = false

    var body: some View {
        Button {
            Task {
                await toggleRecording()
            }
        } label: {
            ZStack {
                // Pulsing ring when recording
                if voiceRecorder.isRecording {
                    Circle()
                        .stroke(ELYTheme.dangerRed.opacity(0.4), lineWidth: 2)
                        .frame(width: 44, height: 44)
                        .scaleEffect(pulseScale)
                        .opacity(2 - pulseScale)
                }

                // Main circle
                Circle()
                    .fill(voiceRecorder.isRecording ? ELYTheme.dangerRed : ELYTheme.cyberCyan)
                    .frame(width: 36, height: 36)

                // Icon
                Image(systemName: voiceRecorder.isRecording ? "stop.fill" : "mic.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(ELYTheme.bgPrimary)
            }
        }
        .onAppear {
            startPulseAnimation()
        }
        .onChange(of: voiceRecorder.isRecording) { _, isRecording in
            if isRecording {
                startPulseAnimation()
            } else {
                pulseScale = 1.0
            }
        }
    }

    // MARK: - Actions

    private func toggleRecording() async {
        if voiceRecorder.isRecording {
            voiceRecorder.stopRecording()
        } else {
            if !permissionsGranted {
                permissionsGranted = await voiceRecorder.requestPermissions()
                guard permissionsGranted else { return }
            }
            voiceRecorder.startRecording()
        }
    }

    // MARK: - Animation

    private func startPulseAnimation() {
        withAnimation(
            .easeInOut(duration: 1.0)
            .repeatForever(autoreverses: false)
        ) {
            pulseScale = 1.6
        }
    }
}

#Preview {
    ZStack {
        ELYTheme.bgPrimary.ignoresSafeArea()
        VoiceInputButton(voiceRecorder: VoiceRecorder())
    }
}
