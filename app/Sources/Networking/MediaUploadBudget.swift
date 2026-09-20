import Foundation

/// One automatic policy: camera uploads yield when fresh voice feedback reports
/// loss or excess RTT. This limits video traffic, never microphone capture.
@MainActor
final class MediaUploadBudget {
    static let shared = MediaUploadBudget()
    private var owners: Set<UUID> = []
    private var lastReports: [String: (time: Double, lost: Int?)] = [:]
    private var bestRTT = Double.infinity
    private var nextSend = 0.0
    private(set) var spacing = 0.0
    private(set) var videoMetrics: [String: Int] = [:]

    func recordVideo(pending: Int, bytes: Int, dropped: Int, uploadedBytes: Int) {
        videoMetrics = ["video_pending_frames": pending, "video_buffered_bytes": bytes,
                        "video_dropped_frames": dropped, "video_uploaded_bytes": uploadedBytes]
    }

    func begin(_ owner: UUID) {
        if owners.isEmpty {
            lastReports.removeAll(); bestRTT = .infinity
            spacing = 0.2; nextSend = 0
        }
        owners.insert(owner)
    }

    func end(_ owner: UUID) {
        owners.remove(owner)
        if owners.isEmpty { spacing = 0; nextSend = 0; lastReports.removeAll() }
    }

    func observe(id: String, timestamp: Double, lost: Int?, rtt: Double?) {
        guard !owners.isEmpty, timestamp.isFinite else { return }
        let previous = lastReports[id]
        guard previous == nil || timestamp > previous!.time else { return }
        if lastReports.count >= 8, previous == nil { lastReports.removeAll() }
        lastReports[id] = (timestamp, lost)
        if let rtt, rtt.isFinite, rtt > 0 { bestRTT = min(bestRTT, rtt) }
        let lossIncreased = lost.map { $0 > (previous?.lost ?? 0) } ?? false
        let delayed = rtt.map { $0.isFinite && $0 > max(0.2, bestRTT * 2) } ?? false
        if lossIncreased || delayed {
            spacing = min(1, max(0.4, spacing * 2))
        } else {
            spacing = max(0.2, spacing - 0.1)
        }
    }

    func waitForTurn() async throws {
        // Short cancellable sleeps let recovered voice conditions take effect.
        while !owners.isEmpty {
            let delay = nextSend - ProcessInfo.processInfo.systemUptime
            if delay <= 0 { break }
            try await Task.sleep(for: .seconds(min(delay, 0.1)))
        }
        try Task.checkCancellation()
        nextSend = ProcessInfo.processInfo.systemUptime + spacing
    }
}
