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

// MARK: - Connection State

enum ConnectionState: Sendable, Equatable {
    case disconnected(reason: String = "")
    case connecting
    case connected
}

// MARK: - WebSocketService

@MainActor
final class WebSocketService: ObservableObject {
    @Published private(set) var connectionState: ConnectionState = .disconnected()
    @Published private(set) var lastMessage: WSMessage?

    /// Callback invoked on each incoming message
    var onMessage: ((WSMessage) -> Void)?

    private var webSocketTask: URLSessionWebSocketTask?
    private var session: URLSession
    private var reconnectAttempt = 0
    private var reconnectTask: Task<Void, Never>?
    private var isManuallyDisconnected = false
    private var currentURL: String = ""
    private var currentToken: String = ""

    private static let maxReconnectDelay: TimeInterval = 30
    private static let baseReconnectDelay: TimeInterval = 2

    init() {
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = true
        self.session = URLSession(configuration: config)
    }

    // MARK: - Public API

    func connect(serverURL: String, token: String) {
        isManuallyDisconnected = false
        currentURL = serverURL
        currentToken = token
        reconnectAttempt = 0
        doConnect()
    }

    func disconnect() {
        isManuallyDisconnected = true
        reconnectTask?.cancel()
        reconnectTask = nil
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        connectionState = .disconnected()
    }

    func send(content: String, conversationId: String? = nil) {
        var pairs: [String: Any] = ["content": content]
        if let convId = conversationId {
            pairs["conversation_id"] = convId
        }
        let json = WSMessage.toJSON(type: "message", pairs: pairs)
        sendRaw(json)
    }

    func sendHitlResponse(actionId: String, decision: String) {
        let json = WSMessage.toJSON(type: "hitl_response", pairs: [
            "action_id": actionId,
            "decision": decision
        ])
        sendRaw(json)
    }

    func sendStop() {
        let json = WSMessage.toJSON(type: "stop", pairs: [:])
        sendRaw(json)
    }

    // MARK: - Private

    private func doConnect() {
        webSocketTask?.cancel(with: .normalClosure, reason: nil)

        let wsURL = currentURL
            .replacingOccurrences(of: "http://", with: "ws://")
            .replacingOccurrences(of: "https://", with: "wss://")
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        // CRIT-2: Token is NOT sent in the URL — it is sent as the first
        // JSON message (handshake) after the WebSocket is accepted.
        let urlString = "\(wsURL)/ws/chat"

        guard let url = URL(string: urlString) else {
            connectionState = .disconnected(reason: "URL invalide")
            return
        }

        connectionState = .connecting

        let task = session.webSocketTask(with: url)
        webSocketTask = task
        task.resume()

        // Send JWT handshake as the first message (same protocol as the web frontend)
        let handshake = WSMessage.toJSON(type: "handshake", pairs: ["token": currentToken])
        task.send(.string(handshake)) { [weak self] error in
            Task { @MainActor in
                if let error {
                    self?.handleDisconnection(reason: error.localizedDescription)
                } else {
                    self?.connectionState = .connected
                    self?.reconnectAttempt = 0
                    // Start listening AFTER handshake is sent
                    self?.listenForMessages()
                }
            }
        }
    }

    private func listenForMessages() {
        webSocketTask?.receive { [weak self] result in
            Task { @MainActor in
                guard let self else { return }
                switch result {
                case .success(let message):
                    switch message {
                    case .string(let text):
                        let wsMsg = WSMessage.parse(text)
                        self.lastMessage = wsMsg
                        self.onMessage?(wsMsg)
                        // If this is our first message, ensure state is connected
                        if self.connectionState != .connected {
                            self.connectionState = .connected
                            self.reconnectAttempt = 0
                        }
                    case .data(let data):
                        if let text = String(data: data, encoding: .utf8) {
                            let wsMsg = WSMessage.parse(text)
                            self.lastMessage = wsMsg
                            self.onMessage?(wsMsg)
                        }
                    @unknown default:
                        break
                    }
                    // Continue listening
                    self.listenForMessages()

                case .failure(let error):
                    self.handleDisconnection(reason: error.localizedDescription)
                }
            }
        }
    }

    private func sendRaw(_ text: String) {
        guard connectionState == .connected || connectionState == .connecting else { return }
        webSocketTask?.send(.string(text)) { error in
            if let error {
                print("[WS] Erreur envoi : \(error.localizedDescription)")
            }
        }
    }

    private func handleDisconnection(reason: String) {
        connectionState = .disconnected(reason: reason)
        webSocketTask = nil

        guard !isManuallyDisconnected else { return }

        // Exponential backoff reconnection
        let delay = min(
            Self.baseReconnectDelay * pow(2.0, Double(reconnectAttempt)),
            Self.maxReconnectDelay
        )
        reconnectAttempt += 1

        print("[WS] Reconnexion dans \(Int(delay))s (tentative \(reconnectAttempt))")

        reconnectTask?.cancel()
        reconnectTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            await self?.doConnect()
        }
    }
}
