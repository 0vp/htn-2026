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
    // Only hide known non-speech annotations. Punctuation around genuine spoken
    // words is not evidence that those words should disappear from the transcript.
    private static let sounds = ["tongue click", "clicks tongue", "click", "sighs", "sigh",
                                 "laughs", "laughter", "coughs", "cough", "breathing"]
    static func spoken(_ raw: String) -> String {
        var text = raw
        for sound in sounds {
            for (open, close) in [("[", "]"), ("(", ")"), ("*", "*")] {
                text = text.replacingOccurrences(of: open + sound + close, with: "", options: .caseInsensitive)
            }
        }
        // Withhold only an unfinished suffix that could still be a known sound.
        if let index = text.lastIndex(where: { "[(*".contains($0) }) {
            let suffix = text[text.index(after: index)...].lowercased()
            if !suffix.isEmpty, sounds.contains(where: { $0.hasPrefix(suffix) }) {
                text = String(text[..<index])
            }
        }
        // A bounded caption may begin in the middle of a recognized annotation.
        for sound in sounds {
            for close in ["]", ")"] {
                if text.lowercased().hasPrefix(sound + close) {
                    text = String(text.dropFirst(sound.count + 1))
                }
            }
        }
        return text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}
