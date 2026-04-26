// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Views/MessageBubble.swift
// @brief      Message bubble component — styled chat message rendering
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

struct MessageBubble: View {
    let message: ChatMessage
    var onSpeak: ((String) -> Void)?

    private var isUser: Bool {
        message.role == .user
    }

    private var displayContent: String {
        message.isStreaming ? message.streamingContent : message.content
    }

    private var timeString: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: message.timestamp)
    }

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if isUser { Spacer(minLength: 48) }

            VStack(alignment: isUser ? .trailing : .leading, spacing: 4) {
                // Message content
                Text(displayContent)
                    .font(.body)
                    .foregroundColor(ELYTheme.textPrimary)
                    .textSelection(.enabled)

                // Tool indicator
                if let toolName = message.toolName, message.isToolActive {
                    HStack(spacing: 4) {
                        ProgressView()
                            .scaleEffect(0.6)
                            .tint(ELYTheme.warningAmber)
                        Text(toolName)
                            .font(.caption2)
                            .foregroundColor(ELYTheme.warningAmber)
                    }
                }

                // Timestamp + speak button
                HStack(spacing: 6) {
                    Text(timeString)
                        .font(.caption2)
                        .foregroundColor(ELYTheme.textMuted)

                    if !isUser && !message.content.isEmpty {
                        Button {
                            onSpeak?(message.content)
                        } label: {
                            Image(systemName: "speaker.wave.2")
                                .font(.caption2)
                                .foregroundColor(ELYTheme.textMuted)
                        }
                    }
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(isUser ? ELYTheme.userBubble : ELYTheme.assistantBubble)
            .clipShape(
                RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusLarge)
            )
            .overlay(
                RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusLarge)
                    .stroke(
                        isUser ? ELYTheme.cyberCyan.opacity(0.2) : ELYTheme.borderDim,
                        lineWidth: 0.5
                    )
            )

            if !isUser { Spacer(minLength: 48) }
        }
        .padding(.horizontal, 12)
    }
}

// MARK: - Streaming Text Bubble (for current response)

struct StreamingBubble: View {
    let content: String
    let activeTool: String?

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            VStack(alignment: .leading, spacing: 4) {
                // Tool indicator
                if let tool = activeTool {
                    HStack(spacing: 4) {
                        ProgressView()
                            .scaleEffect(0.6)
                            .tint(ELYTheme.warningAmber)
                        Text(tool)
                            .font(.caption2)
                            .foregroundColor(ELYTheme.warningAmber)
                    }
                }

                if !content.isEmpty {
                    Text(content)
                        .font(.body)
                        .foregroundColor(ELYTheme.textPrimary)
                        .textSelection(.enabled)
                } else if activeTool == nil {
                    // Typing indicator
                    HStack(spacing: 4) {
                        ForEach(0..<3, id: \.self) { index in
                            Circle()
                                .fill(ELYTheme.cyberCyan.opacity(0.6))
                                .frame(width: 6, height: 6)
                                .offset(y: typingOffset(for: index))
                                .animation(
                                    .easeInOut(duration: 0.5)
                                        .repeatForever()
                                        .delay(Double(index) * 0.15),
                                    value: true
                                )
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(ELYTheme.assistantBubble)
            .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusLarge))
            .overlay(
                RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusLarge)
                    .stroke(ELYTheme.borderDim, lineWidth: 0.5)
            )

            Spacer(minLength: 48)
        }
        .padding(.horizontal, 12)
    }

    private func typingOffset(for index: Int) -> CGFloat {
        return -4
    }
}

// MARK: - HITL Action Card

struct HITLCard: View {
    let request: HitlRequest
    var onApprove: () -> Void
    var onDeny: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Header
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.shield")
                    .foregroundColor(ELYTheme.warningAmber)
                Text("Autorisation requise")
                    .font(.headline)
                    .foregroundColor(ELYTheme.warningAmber)
            }

            // Description
            Text(request.description)
                .font(.body)
                .foregroundColor(ELYTheme.textPrimary)

            // Tool name
            HStack(spacing: 4) {
                Text("Outil :")
                    .font(.caption)
                    .foregroundColor(ELYTheme.textMuted)
                Text(request.tool)
                    .font(.caption)
                    .foregroundColor(ELYTheme.cyberCyan)
                    .fontWeight(.medium)
            }

            // Args (if any)
            if !request.args.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(request.args.sorted(by: { $0.key < $1.key })), id: \.key) { key, value in
                        HStack(spacing: 4) {
                            Text("\(key):")
                                .font(.caption2)
                                .foregroundColor(ELYTheme.textMuted)
                            Text(value)
                                .font(.caption2)
                                .foregroundColor(ELYTheme.textSecondary)
                                .lineLimit(2)
                        }
                    }
                }
                .padding(8)
                .background(ELYTheme.bgPrimary.opacity(0.5))
                .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall))
            }

            // Action buttons
            HStack(spacing: 12) {
                Button {
                    onDeny()
                } label: {
                    Text("Refuser")
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .foregroundColor(ELYTheme.dangerRed)
                        .background(ELYTheme.dangerRed.opacity(0.15))
                        .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall))
                }

                Button {
                    onApprove()
                } label: {
                    Text("Autoriser")
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .foregroundColor(ELYTheme.bgPrimary)
                        .background(ELYTheme.successGreen)
                        .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall))
                }
            }
        }
        .padding(16)
        .background(ELYTheme.bgSecondary)
        .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusMedium))
        .overlay(
            RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusMedium)
                .stroke(ELYTheme.warningAmber.opacity(0.4), lineWidth: 1)
        )
        .padding(.horizontal, 12)
    }
}

#Preview {
    ZStack {
        ELYTheme.bgPrimary.ignoresSafeArea()
        VStack(spacing: 12) {
            MessageBubble(message: ChatMessage(role: .user, content: "Salut !"))
            MessageBubble(message: ChatMessage(role: .assistant, content: "Bonjour, comment puis-je vous aider ?"))
            StreamingBubble(content: "Je suis en train de...", activeTool: nil)
        }
    }
}
