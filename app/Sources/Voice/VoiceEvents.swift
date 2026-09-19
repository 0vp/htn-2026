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

/// Loudness of just the last polling slice, shaped for a mouth.
///
/// WebRTC's `audioLevel` stat is a slow running average, so a face driven by it trails the
/// voice. Its cumulative `totalAudioEnergy` / `totalSamplesDuration` counters give the RMS level
/// of exactly the audio played since the previous poll. The mouth opens at once and closes
/// over roughly 120 ms so it doesn't flicker between syllables.
struct SpeechMeter {
    struct Sample: Equatable {
        let energy: Double
        let duration: Double
        let level: Double
    }
    private var last: Sample?
    private(set) var envelope = 0.0

    mutating func update(_ sample: Sample) -> Double {
        var rms = sample.level
        if let last, sample.duration > last.duration, sample.energy >= last.energy {
            rms = ((sample.energy - last.energy) / (sample.duration - last.duration)).squareRoot()
        }
        last = sample
        let target = min(1, max(0, rms - 0.008) * 7)
        envelope = target > envelope ? target : envelope * 0.55 + target * 0.45
        if envelope < 0.02 { envelope = 0 }
        return envelope
    }
}

enum Caption {
    /// GPT-Live transcribes some non-speech sounds as annotations such as "[tongue click]",
    /// "(clicks tongue)" or "*sighs*". Captions show spoken words only. An annotation can arrive
    /// split across several deltas, so this cleans the whole accumulated text and hides an
    /// unfinished one until it closes.
    static func spoken(_ raw: String) -> String {
        var words = ""
        var closing: Character?
        // Trimming old text can cut into an annotation; drop that fragment up to its closer.
        var text = Substring(raw)
        if let close = text.firstIndex(where: { "])".contains($0) }),
           !text[..<close].contains(where: { "[(".contains($0) }) {
            text = text[text.index(after: close)...]
        }
        for character in text {
            if let end = closing {
                if character == end { closing = nil }
                continue
            }
            switch character {
            case "[": closing = "]"
            case "(": closing = ")"
            case "*": closing = "*"
            case "]", ")": continue  // stray closer with no opener
            default: words.append(character)
            }
        }
        return words.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}
