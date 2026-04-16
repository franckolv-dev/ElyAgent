// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Views/ChatView.swift
// @brief      Main chat view — message list and input
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
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

struct ChatView: View {
    @EnvironmentObject private var authVM: AuthViewModel
    @StateObject private var chatVM = ChatViewModel()
    @State private var showConversationList = false
    @State private var showSettings = false
    @State private var showVoiceMode = false
    @FocusState private var isInputFocused: Bool

    var body: some View {
        ZStack {
            ELYTheme.bgPrimary
                .ignoresSafeArea()

            VStack(spacing: 0) {
                // Messages area
                messagesView

                // Input area
                inputArea
            }
        }
        .navigationTitle("ELY")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(ELYTheme.bgSecondary, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button {
                    showConversationList = true
                } label: {
                    Image(systemName: "sidebar.left")
                        .foregroundColor(ELYTheme.cyberCyan)
                }
            }

            ToolbarItem(placement: .topBarTrailing) {
                HStack(spacing: 12) {
                    // Connection indicator
                    connectionIndicator

                    // New conversation
                    Button {
                        chatVM.newConversation()
                    } label: {
                        Image(systemName: "square.and.pencil")
                            .foregroundColor(ELYTheme.cyberCyan)
                    }

                    // Settings
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                            .foregroundColor(ELYTheme.textSecondary)
                    }
                }
            }
        }
        .sheet(isPresented: $showConversationList) {
            ConversationList(chatVM: chatVM)
                .environmentObject(authVM)
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
                .environmentObject(authVM)
        }
        .fullScreenCover(isPresented: $showVoiceMode) {
            VoiceModeView(chatVM: chatVM)
        }
        .onAppear {
            chatVM.setup(authService: authVM.authService)
        }
    }

    // MARK: - Connection Indicator

    @ViewBuilder
    private var connectionIndicator: some View {
        switch chatVM.connectionState {
        case .connected:
            Circle()
                .fill(ELYTheme.successGreen)
                .frame(width: 8, height: 8)
        case .connecting:
            ProgressView()
                .scaleEffect(0.6)
                .tint(ELYTheme.warningAmber)
        case .disconnected:
            Circle()
                .fill(ELYTheme.dangerRed)
                .frame(width: 8, height: 8)
        }
    }

    // MARK: - Messages

    private var messagesView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    ForEach(chatVM.messages) { message in
                        MessageBubble(message: message) { text in
                            chatVM.speakMessage(text)
                        }
                        .id(message.id)
                    }

                    // Streaming bubble
                    if chatVM.isStreaming {
                        StreamingBubble(
                            content: chatVM.streamingContent,
                            activeTool: chatVM.activeTool
                        )
                        .id("streaming")
                    }

                    // HITL Card
                    if let hitl = chatVM.hitlPending {
                        HITLCard(
                            request: hitl,
                            onApprove: {
                                chatVM.respondToHitl(actionId: hitl.actionId, decision: "approve")
                            },
                            onDeny: {
                                chatVM.respondToHitl(actionId: hitl.actionId, decision: "deny")
                            }
                        )
                        .id("hitl")
                    }

                    // Error
                    if let error = chatVM.errorMessage {
                        Text(error)
                            .font(.caption)
                            .foregroundColor(ELYTheme.dangerRed)
                            .padding(.horizontal, 16)
                            .id("error")
                    }

                    // Spacer at bottom for scroll
                    Color.clear
                        .frame(height: 1)
                        .id("bottom")
                }
                .padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: chatVM.messages.count) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo("bottom", anchor: .bottom)
                }
            }
            .onChange(of: chatVM.streamingContent) { _, _ in
                withAnimation(.easeOut(duration: 0.1)) {
                    proxy.scrollTo("streaming", anchor: .bottom)
                }
            }
            .onChange(of: chatVM.hitlPending?.id) { _, _ in
                if chatVM.hitlPending != nil {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo("hitl", anchor: .bottom)
                    }
                }
            }
        }
    }

    // MARK: - Input Area

    private var inputArea: some View {
        VStack(spacing: 0) {
            Divider()
                .background(ELYTheme.borderDim)

            // Tool activity bar
            if let tool = chatVM.activeTool {
                HStack(spacing: 6) {
                    ProgressView()
                        .scaleEffect(0.6)
                        .tint(ELYTheme.warningAmber)
                    Text(tool)
                        .font(.caption)
                        .foregroundColor(ELYTheme.warningAmber)
                    Spacer()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 6)
                .background(ELYTheme.bgSecondary)
            }

            HStack(alignment: .bottom, spacing: 8) {
                // Mic button
                VoiceInputButton(voiceRecorder: chatVM.voiceRecorder)

                // Text input
                TextField("Message...", text: $chatVM.inputText, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.body)
                    .foregroundColor(ELYTheme.textPrimary)
                    .lineLimit(1...6)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(ELYTheme.bgSecondary)
                    .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusPill))
                    .overlay(
                        RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusPill)
                            .stroke(ELYTheme.borderDim, lineWidth: 1)
                    )
                    .focused($isInputFocused)

                // Send / Stop button
                if chatVM.isStreaming {
                    Button {
                        chatVM.stopGeneration()
                    } label: {
                        Image(systemName: "stop.circle.fill")
                            .font(.system(size: 28))
                            .foregroundColor(ELYTheme.dangerRed)
                    }
                } else {
                    Button {
                        let text = chatVM.inputText
                        chatVM.send(content: text)
                        isInputFocused = false
                    } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 28))
                            .foregroundColor(
                                chatVM.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                    ? ELYTheme.textMuted
                                    : ELYTheme.cyberCyan
                            )
                    }
                    .disabled(chatVM.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }

                // Voice mode button
                Button {
                    showVoiceMode = true
                } label: {
                    Image(systemName: "waveform")
                        .font(.system(size: 18))
                        .foregroundColor(ELYTheme.cyberCyan)
                        .frame(width: 28, height: 28)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(ELYTheme.bgPrimary)
        }
    }
}

#Preview {
    NavigationStack {
        ChatView()
            .environmentObject(AuthViewModel())
    }
}
