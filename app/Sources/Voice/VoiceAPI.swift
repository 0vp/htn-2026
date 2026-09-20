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
    @MainActor func transport() -> any VoiceTransport
}

extension VoiceServing { @MainActor func transport() -> any VoiceTransport { VoicePeer() } }

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
        let reliable = sdp.hasPrefix("reliable-audio-v1:")
        var request = URLRequest(url: endpoint(reliable ? "reliable/sessions" : "sessions"))
        request.httpMethod = "POST"
        var body: [String: Any] = ["device_id": device, "codex_enabled": codex,
                                  "request_id": reliable ? String(sdp.dropFirst("reliable-audio-v1:".count)) : requestID]
        if !reliable { body["sdp"] = sdp }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await perform(request)
    }

    func end(sessionID: String) async throws {
        if sessionID.hasPrefix("buffered-") {
            _ = try await finishReliable(sessionID, next: 0) // Idempotent after drain; also closes late empty creations.
            return
        }
        // Session IDs are opaque; never interpolate them into paths.
        var request = URLRequest(url: endpoint("end"))
        request.httpMethod = "POST"
        request.httpBody = try JSONSerialization.data(withJSONObject: ["device_id": device, "session_id": sessionID])
        let _: EndReceipt = try await perform(request)
    }

    /// Direct phone-to-OpenAI WebRTC keeps GPT-Live's latency low; the server joins the same
    /// session over a sideband socket for delegation and tool work. The buffered relay through
    /// the server stays available behind the `voiceReliableTransport` default.
    @MainActor func transport() -> any VoiceTransport {
        UserDefaults.standard.bool(forKey: "voiceReliableTransport") ? ReliableVoicePeer(api: self) : VoicePeer()
    }
    func finishReliable(_ ident: String, next: Int) async throws -> String {
        var request = URLRequest(url: endpoint("reliable/end"))
        request.httpMethod = "POST"
        request.timeoutInterval = 150
        request.httpBody = try JSONSerialization.data(withJSONObject: ["device_id": device, "session_id": ident, "next_seq": next])
        let receipt: ReliableEndReceipt = try await perform(request)
        return receipt.turns.map(\.text).joined(separator: " ")
    }
    private struct ReliableEndReceipt: Decodable {
        struct Turn: Decodable { let text: String }
        let ended: Bool
        let turns: [Turn]
    }
    private struct EndReceipt: Decodable { let ended: Bool }
    private func endpoint(_ path: String) -> URL {
        base.appendingPathComponent("v1/rooms/\(room)/voice/\(path)")
    }
    private func perform<T: Decodable>(_ original: URLRequest) async throws -> T {
        var request = original
        if !request.url!.path.hasSuffix("reliable/end") { request.timeoutInterval = 25 }
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
