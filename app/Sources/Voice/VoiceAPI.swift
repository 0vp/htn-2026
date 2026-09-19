import Foundation

struct VoiceCapabilities: Decodable {
    let available: Bool
    let codex_available: Bool
}

struct VoiceSession: Decodable {
    let session_id: String
    let sdp: String
    let codex_enabled: Bool
}

protocol VoiceServing {
    func capabilities() async throws -> VoiceCapabilities
    func create(sdp: String, codex: Bool, requestID: String) async throws -> VoiceSession
    func end(sessionID: String) async throws
}

/// Room-bound signaling only. The OpenAI key and delegation policy stay on the server.
struct VoiceAPI: VoiceServing {
    let base: URL
    let room: String
    let device: String
    var session: URLSession = .shared

    func capabilities() async throws -> VoiceCapabilities {
        var components = URLComponents(url: endpoint("capabilities"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "device_id", value: device)]
        return try await perform(URLRequest(url: components.url!))
    }

    func create(sdp: String, codex: Bool, requestID: String) async throws -> VoiceSession {
        var request = URLRequest(url: endpoint("sessions"))
        request.httpMethod = "POST"
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "device_id": device, "codex_enabled": codex, "sdp": sdp, "request_id": requestID
        ])
        return try await perform(request)
    }

    func end(sessionID: String) async throws {
        // Session IDs are opaque; never interpolate them into paths.
        var request = URLRequest(url: endpoint("end"))
        request.httpMethod = "POST"
        request.httpBody = try JSONSerialization.data(withJSONObject: ["device_id": device, "session_id": sessionID])
        let _: EndReceipt = try await perform(request)
    }

    private struct EndReceipt: Decodable { let ended: Bool }
    private func endpoint(_ path: String) -> URL {
        base.appendingPathComponent("v1/rooms/\(room)/voice/\(path)")
    }
    private func perform<T: Decodable>(_ original: URLRequest) async throws -> T {
        var request = original
        request.timeoutInterval = 25
        request.networkServiceType = .responsiveData
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard (200..<300).contains(http.statusCode) else {
            let message: String
            switch http.statusCode {
            case 404, 501: message = "Voice is not installed on the room server yet."
            case 503: message = "Voice is unavailable on the server. Try again shortly."
            case 403: message = "Only the room leader can start voice."
            case 409: message = "The previous conversation is still ending. Try again shortly."
            case 429: message = "Voice is busy. Try again shortly."
            default: message = "Could not connect to voice (\(http.statusCode))."
            }
            throw APIError(message: message)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
