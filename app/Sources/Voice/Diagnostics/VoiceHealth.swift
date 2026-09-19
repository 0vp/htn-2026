import Foundation

/// Sample progress distinguishes silence from capture stopping. Packet counters alone
/// cannot: Opus can send fewer packets during silence without stopping the microphone.
struct VoiceHealth {
    private var previousDuration: Double?
    private var progressAt: TimeInterval?

    mutating func capture(duration: Double?, now: TimeInterval, muted: Bool) -> String {
        guard !muted else {
            previousDuration = nil; progressAt = nil
            return "Mic muted"
        }
        guard let duration, duration.isFinite else {
            previousDuration = nil; progressAt = nil
            return "Capture measurement unavailable"
        }
        if previousDuration == nil || duration < previousDuration! {
            previousDuration = duration; progressAt = now
            return "Measuring capture progress"
        }
        if duration != previousDuration { progressAt = now }
        previousDuration = duration
        if let progressAt, now - progressAt >= 2 { return "Capture counter stalled" }
        return "Capture samples advancing"
    }
}
