import AVFoundation
import WebRTC

/// Native audio-only WebRTC. Camera/LiDAR continue through the capture pipeline.
@MainActor
final class VoicePeer: NSObject, VoiceTransport {
    var receive: ((VoiceEvent) -> Void)?
    private static let sharedFactory = RTCPeerConnectionFactory()
    private let factory: RTCPeerConnectionFactory

    init(factory: RTCPeerConnectionFactory? = nil) {
        self.factory = factory ?? Self.sharedFactory
        super.init()
    }
    private var peer: RTCPeerConnection?
    private var channel: RTCDataChannel?
    private var microphone: RTCAudioTrack?
    private var trace: VoiceTrace?
    private var health = VoiceHealth()
    private var lastHealthAt = -Double.infinity
    private var metering: Task<Void, Never>?
    private var speech = SpeechMeter()
    private var microphoneMeter = SpeechMeter()

    func offer() async throws -> String {
        trace = VoiceTrace()
        try VoiceAudioSession.configure()
        let config = RTCConfiguration()
        config.sdpSemantics = .unifiedPlan
        config.enableDscp = true
        guard let peer = factory.peerConnection(with: config,
            constraints: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil), delegate: self)
        else { throw APIError(message: "Could not prepare voice audio.") }
        self.peer = peer
        let source = factory.audioSource(with: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil))
        let track = factory.audioTrack(with: source, trackId: "microphone")
        // Match the official WebRTC sample: capture continuously and let the transport
        // send as soon as it connects. Waiting for the UI's session.started callback
        // needlessly replaces opening audio with silence. Explicit user mute still applies.
        track.isEnabled = true
        microphone = track
        peer.add(track, streamIds: ["voice"])
        let channel = peer.dataChannel(forLabel: "oai-events", configuration: RTCDataChannelConfiguration())
        guard let channel else { throw APIError(message: "Could not prepare the voice event channel.") }
        self.channel = channel
        channel.delegate = self
        let offer: RTCSessionDescription = try await withCheckedThrowingContinuation { continuation in
            peer.offer(for: RTCMediaConstraints(mandatoryConstraints: ["OfferToReceiveAudio": "true"], optionalConstraints: nil)) { description, error in
                if let error { continuation.resume(throwing: error) }
                else if let description { continuation.resume(returning: description) }
                else { continuation.resume(throwing: URLError(.badServerResponse)) }
            }
        }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            peer.setLocalDescription(offer) { error in
                if let error { continuation.resume(throwing: error) } else { continuation.resume() }
            }
        }
        for _ in 0..<100 {
            try Task.checkCancellation()
            if peer.iceGatheringState == .complete, let sdp = peer.localDescription?.sdp { return sdp }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw APIError(message: "Voice connection timed out. Check your network and retry.")
    }

    func answer(_ sdp: String) async throws {
        guard let peer else { throw CancellationError() }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            peer.setRemoteDescription(RTCSessionDescription(type: .answer, sdp: sdp)) { error in
                if let error { continuation.resume(throwing: error) } else { continuation.resume() }
            }
        }
        prioritizeAudio()
    }
    private func prioritizeAudio() {
        for sender in peer?.senders ?? [] where sender.track?.kind == "audio" {
            let parameters = sender.parameters
            for encoding in parameters.encodings {
                encoding.networkPriority = .high
            }
            sender.parameters = parameters
        }
    }
    func startMetering() {
        metering?.cancel()
        speech = SpeechMeter(); microphoneMeter = SpeechMeter()
        metering = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, let peer = self.peer else { return }
                let report = await withCheckedContinuation { continuation in
                    peer.statistics { continuation.resume(returning: $0) }
                }
                guard !Task.isCancelled, self.peer === peer else { return }
                do {
                    let inbound = report.statistics.values.filter {
                        $0.type == "inbound-rtp" && ($0.values["kind"] as? String == "audio" || $0.values["mediaType"] as? String == "audio")
                    }
                    let source = report.statistics.values.filter {
                        $0.type == "media-source" && ($0.values["kind"] as? String == "audio")
                    }
                    let playout = VoicePeer.sample(inbound)
                    let microphone = VoicePeer.sample(source)
                    let sent = report.statistics.values.filter { $0.type == "outbound-rtp" }
                        .compactMap { ($0.values["packetsSent"] as? NSNumber)?.intValue }.reduce(0, +)
                    let received = inbound.compactMap { ($0.values["packetsReceived"] as? NSNumber)?.intValue }.reduce(0, +)
                    self.receive?(.level(self.speech.update(playout)))
                    self.receive?(.inputLevel(self.microphoneMeter.update(microphone)))
                    self.receive?(.packets(sent, received))
                    self.reportHealth(report, source: source, sent: sent)
                }
                // Mouth frames need ~25 Hz; slower polling made the face trail the voice.
                try? await Task.sleep(for: .milliseconds(40))
            }
        }
    }
    private func reportHealth(_ report: RTCStatisticsReport, source: [RTCStatistics], sent: Int) {
        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastHealthAt >= 1 else { return }
        lastHealthAt = now
        let duration = source.compactMap { ($0.values["totalSamplesDuration"] as? NSNumber)?.doubleValue }.max()
        let muted = microphone?.isEnabled != true
        let capture = health.capture(duration: duration, now: now, muted: muted)
        let remote = report.statistics.values.filter {
            $0.type == "remote-inbound-rtp" && ($0.values["kind"] as? String == "audio" || $0.values["mediaType"] as? String == "audio")
        }
        let loss = remote.compactMap { ($0.values["fractionLost"] as? NSNumber)?.doubleValue }.max()
        let lossText = loss.map { String(format: "last uplink loss %.1f%%", $0 * 100) } ?? "uplink loss unavailable"
        receive?(.diagnostic(capture + " · " + lossText))
        var row: [String: Any] = ["event": "sample", "capture": capture, "muted": muted,
                                  "packets_sent": sent, "ice_state": peer?.iceConnectionState.rawValue ?? -1]
        row["capture_seconds"] = duration
        row["microphone_energy"] = source.compactMap { ($0.values["totalAudioEnergy"] as? NSNumber)?.doubleValue }.max()
        row["microphone_level"] = source.compactMap { ($0.values["audioLevel"] as? NSNumber)?.doubleValue }.max()
        row["uplink_reports"] = remote.map { stat -> [String: Any] in
            var fields: [String: Any] = ["id": stat.id, "timestamp_us": stat.timestamp_us]
            for key in ["packetsLost", "fractionLost", "roundTripTime", "reportsReceived"] {
                fields[key] = stat.values[key]
            }
            return fields
        }
        trace?.write(row)
    }
    /// Cumulative energy counters, plus WebRTC's smoothed level as a fallback before two samples exist.
    nonisolated private static func sample(_ stats: [RTCStatistics]) -> SpeechMeter.Sample {
        func total(_ key: String) -> Double {
            stats.compactMap { ($0.values[key] as? NSNumber)?.doubleValue }.reduce(0, +)
        }
        let level = stats.compactMap { ($0.values["audioLevel"] as? NSNumber)?.doubleValue }.max() ?? 0
        return SpeechMeter.Sample(energy: total("totalAudioEnergy"), duration: total("totalSamplesDuration"), level: level)
    }
    func mute(_ muted: Bool) {
        microphone?.isEnabled = !muted
        trace?.write(["event": "user_mute", "muted": muted])
    }
    func close() {
        metering?.cancel(); metering = nil
        trace?.stop(); trace = nil
        microphone?.isEnabled = false
        if channel?.readyState == .open {
            channel?.sendData(RTCDataBuffer(data: Data(#"{"type":"session.close"}"#.utf8), isBinary: false))
        }
        channel?.delegate = nil
        channel?.close()
        peer?.delegate = nil
        peer?.close()
        channel = nil; peer = nil; microphone = nil
        // Server /voice/end is the authoritative hangup; data-channel delivery is best effort.
    }
}

extension VoicePeer: RTCPeerConnectionDelegate, RTCDataChannelDelegate {
    nonisolated func dataChannelDidChangeState(_ dataChannel: RTCDataChannel) {
        if dataChannel.readyState == .closed { Task { @MainActor [weak self] in self?.receive?(.lost) } }
    }
    nonisolated func dataChannel(_ dataChannel: RTCDataChannel, didReceiveMessageWith buffer: RTCDataBuffer) {
        guard let event = VoiceEvent.decode(buffer.data) else { return }
        Task { @MainActor [weak self] in if event == .ready { self?.startMetering() }; self?.receive?(event) }
    }
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {
        if newState == .failed || newState == .disconnected {
            Task { @MainActor [weak self] in self?.receive?(.lost) }
        }
    }
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}
    nonisolated func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {}
}
