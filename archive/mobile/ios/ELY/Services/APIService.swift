// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Services/APIService.swift
// @brief      REST API client — HTTP requests, response decoding
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

// MARK: - API Errors

enum APIError: LocalizedError, Sendable {
    case invalidURL
    case unauthorized
    case serverError(Int, String)
    case decodingError(String)
    case networkError(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "URL invalide"
        case .unauthorized:
            return "Non autorisé"
        case .serverError(let code, let msg):
            return "Erreur serveur (\(code)) : \(msg)"
        case .decodingError(let msg):
            return "Erreur de décodage : \(msg)"
        case .networkError(let msg):
            return "Erreur réseau : \(msg)"
        }
    }
}

// MARK: - Transcription Response

struct TranscribeResponse: Codable, Sendable {
    let text: String
    let language: String?
}

// MARK: - APIService

final class APIService: Sendable {
    private let serverURL: String
    private let token: String

    init(serverURL: String, token: String) {
        self.serverURL = serverURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        self.token = token
    }

    // MARK: - Conversations

    func fetchConversations() async throws -> [Conversation] {
        let data = try await get(path: "/api/conversations")
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        do {
            return try decoder.decode([Conversation].self, from: data)
        } catch {
            throw APIError.decodingError(error.localizedDescription)
        }
    }

    // MARK: - Conversation Messages

    func fetchMessages(conversationId: String) async throws -> [ChatMessage] {
        let data = try await get(path: "/api/conversations/\(conversationId)/messages")
        guard let jsonArray = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            throw APIError.decodingError("Format de messages invalide")
        }

        return jsonArray.compactMap { dict -> ChatMessage? in
            guard let id = dict["id"] as? String,
                  let roleStr = dict["role"] as? String,
                  let content = dict["content"] as? String else { return nil }

            let role: MessageRole = roleStr == "user" ? .user : .assistant
            let convId = dict["conversation_id"] as? String ?? conversationId

            return ChatMessage(
                id: id,
                conversationId: convId,
                role: role,
                content: content
            )
        }
    }

    // MARK: - Transcription

    func transcribe(audioData: Data, filename: String = "audio.m4a") async throws -> TranscribeResponse {
        let boundary = UUID().uuidString
        guard let url = URL(string: "\(serverURL)/api/transcribe") else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/mp4\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(TranscribeResponse.self, from: data)
    }

    // MARK: - TTS Audio

    func fetchTTSAudio(text: String) async throws -> Data {
        guard let url = URL(string: "\(serverURL)/tts/speak") else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30

        let body: [String: String] = ["text": text]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)
        try validateResponse(response, data: data)
        return data
    }

    // MARK: - Private Helpers

    private func get(path: String) async throws -> Data {
        guard let url = URL(string: "\(serverURL)\(path)") else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 15

        let (data, response) = try await URLSession.shared.data(for: request)
        try validateResponse(response, data: data)
        return data
    }

    private func validateResponse(_ response: URLResponse, data: Data) throws {
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.networkError("Réponse invalide")
        }

        switch httpResponse.statusCode {
        case 200...299:
            return
        case 401:
            throw APIError.unauthorized
        default:
            let msg = String(data: data, encoding: .utf8) ?? "Erreur inconnue"
            throw APIError.serverError(httpResponse.statusCode, msg)
        }
    }
}
