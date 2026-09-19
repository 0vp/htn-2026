import Foundation

enum VoiceEvent: Equatable {
    case ready, closed, lost
    case level(Double)
    case inputLevel(Double)
    case packets(Int, Int)
    case transcript(String, String)
    case failure(String)

    static func decode(_ data: Data) -> VoiceEvent? {
        guard let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = event["type"] as? String else { return nil }
        switch type {
        case "session.started": return .ready
        case "session.closed": return .closed
        case "session.input_transcript.delta", "session.output_transcript.delta":
            guard let delta = event["delta"] as? String else { return nil }
            return .transcript(type == "session.input_transcript.delta" ? "You" : "Assistant", delta)
        case "error", "session.error": return .failure("The voice service reported an error. End the call and retry.")
        default: return nil
        }
    }
}

@MainActor
protocol VoiceTransport: AnyObject {
    var receive: ((VoiceEvent) -> Void)? { get set }
    func offer() async throws -> String
    func answer(_ sdp: String) async throws
    func mute(_ muted: Bool)
    func close()
}
