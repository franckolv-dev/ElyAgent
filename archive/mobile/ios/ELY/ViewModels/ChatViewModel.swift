// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/ViewModels/ChatViewModel.swift
// @brief      Chat view model — message flow, WebSocket events, agent state
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
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var isStreaming: Bool = false
    @Published var streamingContent: String = ""
    @Published var conversationId: String?
    @Published var activeTool: String?
    @Published var hitlPending: HitlRequest?
    @Published var inputText: String = ""
    @Published var errorMessage: String?

    let wsService = WebSocketService()
    let ttsService = TTSService()
    let voiceRecorder = VoiceRecorder()

    private var authService: AuthService?
    private var streamingMessageId: String?

    var connectionState: ConnectionState {
        wsService.connectionState
    }

    // MARK: - Setup

    func setup(authService: AuthService) {
        self.authService = authService

        wsService.onMessage = { [weak self] msg in
            self?.handleWSMessage(msg)
        }

        voiceRecorder.onTranscriptReady = { [weak self] transcript in
            guard let self else { return }
            self.inputText = transcript
            self.send(content: transcript)
        }

        connect()
    }

    // MARK: - Connection

    func connect() {
        guard let auth = authService,
              let token = auth.accessToken,
              !auth.serverURL.isEmpty else {
            return
        }

        wsService.connect(serverURL: auth.serverURL, token: token)
    }

    func disconnect() {
        wsService.disconnect()
    }

    // MARK: - Send Message

    func send(content: String) {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Add user message locally
        let userMessage = ChatMessage(
            conversationId: conversationId ?? "",
            role: .user,
            content: trimmed
        )
        messages.append(userMessage)

        // Clear input
        inputText = ""

        // Send via WebSocket
        wsService.send(content: trimmed, conversationId: conversationId)
    }

    // MARK: - HITL Response

    func respondToHitl(actionId: String, decision: String) {
        wsService.sendHitlResponse(actionId: actionId, decision: decision)
        hitlPending = nil
    }

    // MARK: - Stop Generation

    func stopGeneration() {
        wsService.sendStop()
    }

    // MARK: - Load Conversation

    func loadConversation(_ conversation: Conversation) async {
        guard let auth = authService,
              let token = auth.accessToken else { return }

        conversationId = conversation.id

        let api = APIService(serverURL: auth.serverURL, token: token)
        do {
            messages = try await api.fetchMessages(conversationId: conversation.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - New Conversation

    func newConversation() {
        conversationId = nil
        messages = []
        streamingContent = ""
        isStreaming = false
        activeTool = nil
        hitlPending = nil
        errorMessage = nil
    }

    // MARK: - Transcribe via Server

    func transcribeServerSide() async {
        guard let auth = authService,
              let token = auth.accessToken,
              let audioData = voiceRecorder.getRecordingData() else { return }

        let api = APIService(serverURL: auth.serverURL, token: token)
        do {
            let response = try await api.transcribe(audioData: audioData)
            let text = response.text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty {
                inputText = text
                send(content: text)
            }
        } catch {
            errorMessage = "Erreur transcription : \(error.localizedDescription)"
        }
    }

    // MARK: - TTS

    func speakMessage(_ text: String) {
        guard let auth = authService,
              let token = auth.accessToken else { return }

        ttsService.speak(text: text, serverURL: auth.serverURL, token: token)
    }

    // MARK: - Handle WebSocket Messages

    private func handleWSMessage(_ msg: WSMessage) {
        switch msg {
        case .start(let convId):
            if let convId {
                conversationId = convId
            }
            isStreaming = true
            streamingContent = ""
            streamingMessageId = UUID().uuidString
            activeTool = nil

        case .token(let content):
            streamingContent += content

        case .message(let id, let content, let convId):
            // Finalize the streamed message
            isStreaming = false

            let finalContent = content.isEmpty ? streamingContent : content
            let message = ChatMessage(
                id: id,
                conversationId: convId ?? conversationId ?? "",
                role: .assistant,
                content: finalContent
            )
            messages.append(message)

            if let convId {
                conversationId = convId
            }

            streamingContent = ""
            streamingMessageId = nil
            activeTool = nil

        case .error(let message):
            isStreaming = false
            streamingContent = ""
            activeTool = nil
            errorMessage = message

        case .toolStart(let tool):
            activeTool = tool

        case .toolEnd:
            activeTool = nil

        case .hitlPending(let actionId, let tool, let description, let args):
            let request = HitlRequest(
                actionId: actionId,
                tool: tool,
                description: description,
                args: args
            )
            hitlPending = request

        case .hitlResolved:
            hitlPending = nil

        case .stopped:
            isStreaming = false
            streamingContent = ""
            activeTool = nil

        case .unknown:
            break
        }
    }
}
