import CryptoKit
import Foundation

/// Reliable phone-to-server audio. Live playback and final captions share the
/// connection, but camera upload scheduling and audio storage are independent.
@MainActor
final class ReliableVoicePeer: VoiceTransport {
    var receive: ((VoiceEvent) -> Void)?
    private let api: VoiceAPI
    private let audio: any BufferedVoiceAudio
    private var spool: AudioSpool?
    private var socket: URLSessionWebSocketTask?
    private var worker: Task<Void, Never>?
    private var reader: Task<Void, Never>?
    private var ident: String?
    private var stopped = false
    private var finishing = false
    private let owner = UUID()
    private var received = 0
    private var capturedSeconds = 0.0
    private var lastTrace = 0.0
    private var trace: VoiceTrace?
    private(set) var finalizedTranscript: String?

    init(api: VoiceAPI, audio: any BufferedVoiceAudio = BufferedAudioDevice()) {
        self.api = api; self.audio = audio
    }
    func offer() async throws -> String {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let digest = SHA256.hash(data: Data("\(api.base)|\(api.room)|\(api.device)".utf8))
            .map { String(format: "%02x", $0) }.joined()
        let spool = try AudioSpool(directory: root.appendingPathComponent("VoiceQueue/\(digest)"))
        self.spool = spool
        trace = VoiceTrace()
        MediaUploadBudget.shared.begin(owner)
        audio.captured = { [weak self, spool] pcm, level in
            do {
                try spool.append(pcm)
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.capturedSeconds += Double(pcm.count) / 48000
                    self.receive?(.inputLevel(level))
                    self.recordCapture()
                }
            } catch {
                Task { @MainActor [weak self] in self?.receive?(.failure(error.localizedDescription)) }
            }
        }
        audio.failed = { [weak self] text in Task { @MainActor in self?.receive?(.failure(text)) } }
        audio.outputLevel = { [weak self] level in Task { @MainActor in self?.receive?(.level(level)) } }
        try audio.start()
        return "reliable-audio-v1:" + spool.requestID
    }
    func answer(_ sdp: String) async throws {
        guard sdp.hasPrefix("buffered-") else { throw APIError(message: "Reliable voice is unavailable on the server.") }
        ident = sdp
        worker = Task { [weak self] in await self?.upload() }
    }
    private func upload() async {
        guard let spool, let ident else { return }
        while !Task.isCancelled, !stopped {
            do {
                var components = URLComponents(url: api.base.appendingPathComponent(
                    "v1/rooms/\(api.room)/voice/reliable/stream/\(ident)"), resolvingAgainstBaseURL: false)!
                components.scheme = components.scheme == "https" ? "wss" : "ws"
                components.queryItems = [URLQueryItem(name: "device_id", value: api.device)]
                var request = URLRequest(url: components.url!)
                request.networkServiceType = .responsiveData
                let socket = URLSession.shared.webSocketTask(with: request)
                socket.priority = URLSessionTask.highPriority
                self.socket = socket; socket.resume()
                let first = try await socket.receive()
                try handle(first, spool: spool)
                receive?(.recovering(false))
                reader = Task { [weak self] in
                    do {
                        while !Task.isCancelled {
                            let event = try await socket.receive()
                            try self?.handle(event, spool: spool)
                        }
                    } catch let error as APIError {
                        self?.receive?(.failure(error.localizedDescription))
                        socket.cancel(with: .goingAway, reason: nil)
                    } catch {
                        socket.cancel(with: .goingAway, reason: nil)
                    }
                }
                var sent = spool.counts().acknowledged
                var lastAck = sent
                var progressedAt = ProcessInfo.processInfo.systemUptime
                while !Task.isCancelled, !stopped {
                    let counts = spool.counts()
                    if counts.acknowledged != lastAck {
                        lastAck = counts.acknowledged
                        progressedAt = ProcessInfo.processInfo.systemUptime
                        receive?(.packets(lastAck, received))
                        receive?(.diagnostic("Audio saved on server: \(lastAck) chunks · waiting: \(counts.next-lastAck)"))
                    }
                    if sent > lastAck, ProcessInfo.processInfo.systemUptime - progressedAt > 5 {
                        throw URLError(.timedOut)
                    }
                    guard sent - lastAck < 8, let chunk = try spool.chunk(sent) else {
                        try await Task.sleep(for: .milliseconds(20)); continue
                    }
                    if sent == lastAck { progressedAt = ProcessInfo.processInfo.systemUptime }
                    let payload = try JSONSerialization.data(withJSONObject: ["type": "audio",
                        "seq": sent, "audio": chunk.base64EncodedString()])
                    try await socket.send(.string(String(decoding: payload, as: UTF8.self)))
                    sent += 1
                }
            } catch let error as APIError {
                receive?(.failure(error.localizedDescription)); close(); return
            } catch {
                reader?.cancel(); socket?.cancel(with: .goingAway, reason: nil); socket = nil
                if stopped || Task.isCancelled { return }
                receive?(.recovering(true))
                receive?(.diagnostic("Connection interrupted. Audio is buffered on this phone and will retry."))
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }
    private func handle(_ message: URLSessionWebSocketTask.Message, spool: AudioSpool) throws {
        let data: Data
        switch message { case .data(let value): data = value; case .string(let value): data = Data(value.utf8); @unknown default: return }
        guard let event = try JSONSerialization.jsonObject(with: data) as? [String: Any], let type = event["type"] as? String else { return }
        switch type {
        case "ack":
            guard let next = event["next_seq"] as? Int else { throw URLError(.badServerResponse) }
            try spool.accept(next)
        case "ready": receive?(.ready)
        case "status": receive?(.diagnostic(event["text"] as? String ?? "Audio pending"))
        case "fatal": receive?(.failure(event["text"] as? String ?? "Audio transfer failed."))
        case "final":
            let turns = event["turns"] as? [[String: Any]] ?? []
            finalizedTranscript = turns.compactMap { $0["text"] as? String }.joined(separator: " ")
            receive?(.finalTranscript(finalizedTranscript!))
            let results = turns.compactMap { $0["result"] as? String }.joined(separator: "\n")
            if !results.isEmpty { receive?(.diagnostic(results)) }
        case "session.output_audio.delta":
            if let value = event["delta"] as? String, let pcm = Data(base64Encoded: value) {
                received += 1; audio.play(pcm)
            }
        case "session.output_transcript.delta":
            if let delta = event["delta"] as? String { receive?(.transcript("Assistant", delta)) }
        default: break
        }
    }
    private func recordCapture() {
        let now = ProcessInfo.processInfo.systemUptime
        guard now-lastTrace >= 1, let counts = spool?.counts() else { return }
        lastTrace = now
        var fields: [String: Any] = ["event": "sample", "transport": "reliable_websocket",
            "capture_seconds": capturedSeconds, "audio_pending_bytes": counts.bytes,
            "audio_captured_chunks": counts.next, "audio_acknowledged_chunks": counts.acknowledged]
        for (key, value) in MediaUploadBudget.shared.videoMetrics { fields[key] = value }
        trace?.write(fields)
    }
    func mute(_ muted: Bool) { audio.mute(muted) }
    func finish() async throws {
        guard !finishing else { return }
        finishing = true
        await audio.stop()
        guard let spool, let ident else { close(); return }
        let deadline = ProcessInfo.processInfo.systemUptime + 30
        while spool.counts().acknowledged != spool.counts().next {
            guard ProcessInfo.processInfo.systemUptime < deadline else {
                close()
                throw APIError(message: "Unsent audio is saved on this phone. Tap Talk to resume uploading.")
            }
            try await Task.sleep(for: .milliseconds(50))
        }
        finalizedTranscript = try await api.finishReliable(ident, next: spool.counts().next)
        try spool.removeIfEmpty()
        close()
    }
    func close() {
        stopped = true
        trace?.stop(); trace = nil
        worker?.cancel(); reader?.cancel()
        socket?.cancel(with: .normalClosure, reason: nil)
        Task { await audio.stop() }
        MediaUploadBudget.shared.end(owner)
    }
}
