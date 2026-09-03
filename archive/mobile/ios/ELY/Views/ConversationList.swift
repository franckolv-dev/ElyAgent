// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Views/ConversationList.swift
// @brief      Conversation list view — history and thread selection
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

import SwiftUI

struct ConversationList: View {
    @ObservedObject var chatVM: ChatViewModel
    @EnvironmentObject private var authVM: AuthViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var conversations: [Conversation] = []
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ZStack {
                ELYTheme.bgPrimary
                    .ignoresSafeArea()

                if isLoading && conversations.isEmpty {
                    ProgressView()
                        .tint(ELYTheme.cyberCyan)
                } else if conversations.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "bubble.left.and.bubble.right")
                            .font(.system(size: 40))
                            .foregroundColor(ELYTheme.textMuted)
                        Text("Aucune conversation")
                            .font(.headline)
                            .foregroundColor(ELYTheme.textMuted)
                    }
                } else {
                    List {
                        ForEach(conversations) { conversation in
                            ConversationRow(conversation: conversation)
                                .listRowBackground(
                                    chatVM.conversationId == conversation.id
                                        ? ELYTheme.cyberCyan.opacity(0.1)
                                        : ELYTheme.bgSecondary
                                )
                                .listRowSeparatorTint(ELYTheme.borderDim)
                                .onTapGesture {
                                    Task {
                                        await chatVM.loadConversation(conversation)
                                        dismiss()
                                    }
                                }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }

                // Error
                if let error = errorMessage {
                    VStack {
                        Spacer()
                        Text(error)
                            .font(.caption)
                            .foregroundColor(ELYTheme.dangerRed)
                            .padding()
                            .background(ELYTheme.bgSecondary)
                            .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusSmall))
                            .padding()
                    }
                }
            }
            .navigationTitle("Conversations")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(ELYTheme.bgSecondary, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Fermer") {
                        dismiss()
                    }
                    .foregroundColor(ELYTheme.cyberCyan)
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        chatVM.newConversation()
                        dismiss()
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "plus")
                            Text("Nouveau")
                        }
                        .foregroundColor(ELYTheme.cyberCyan)
                    }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .task {
            await loadConversations()
        }
    }

    // MARK: - Load

    private func loadConversations() async {
        guard let token = authVM.authService.accessToken else { return }

        isLoading = true
        errorMessage = nil

        let api = APIService(serverURL: authVM.authService.serverURL, token: token)
        do {
            conversations = try await api.fetchConversations()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}

// MARK: - Conversation Row

struct ConversationRow: View {
    let conversation: Conversation

    private var dateString: String {
        let formatter = RelativeDateTimeFormatter()
        formatter.locale = Locale(identifier: "fr-FR")
        formatter.unitsStyle = .short
        return formatter.localizedString(for: conversation.updatedAt, relativeTo: Date())
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(conversation.title)
                .font(.body)
                .fontWeight(.medium)
                .foregroundColor(ELYTheme.textPrimary)
                .lineLimit(2)

            HStack(spacing: 8) {
                Text(dateString)
                    .font(.caption)
                    .foregroundColor(ELYTheme.textMuted)

                if conversation.messageCount > 0 {
                    Text("\(conversation.messageCount) messages")
                        .font(.caption)
                        .foregroundColor(ELYTheme.textMuted)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

#Preview {
    ConversationList(chatVM: ChatViewModel())
        .environmentObject(AuthViewModel())
}
