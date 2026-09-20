import UIKit
import WebRTC
import XCTest
@testable import HTNApp

/// Opt-in billed soak: a generated voice.pcm bundle resource enables this test.
/// Sustains 5 full-size depth packets/s for two minutes, independent of AR tracking.
/// Tests upload/capture continuity; synthetic audio bypasses microphone DSP.
final class VoiceSoakTests: XCTestCase {
    @MainActor func testSustainedUploadsAndVoice() async throws { try await run(slowReceiver: false) }
    @MainActor func testSlowReceiverAndVoice() async throws { try await run(slowReceiver: true) }

    @MainActor private func run(slowReceiver: Bool) async throws {
        guard let fixture = Bundle(for: Self.self).url(forResource: "voice", withExtension: "pcm") else {
            throw XCTSkip("Explicit speech fixture not supplied")
        }
        let oldIdle = UIApplication.shared.isIdleTimerDisabled
        UIApplication.shared.isIdleTimerDisabled = true
        defer { UIApplication.shared.isIdleTimerDisabled = oldIdle }
        let rooms = RoomAPI(), id = "voice-soak-\(UUID().uuidString)"
        let room = try await rooms.create(name: "Synthetic voice upload soak", device: id)
        let api = VoiceAPI(base: rooms.base, room: room.id, device: id)
        let stream = FrameStream(base: rooms.base, room: room.id, device: id)
        let transportStart = ProcessInfo.processInfo.systemUptime
        let uploads = UploadQueue { data, header in
            try await stream.send(data, header: header)
            // Simulate increasingly backlogged frame completion while voice continues.
            // This is application backpressure, not a claim to emulate Wi-Fi loss.
            if slowReceiver, ProcessInfo.processInfo.systemUptime - transportStart >= 60 {
                try await Task.sleep(for: .milliseconds(800))
            }
        }
        let audio = FixtureAudioDevice(pcm: try Data(contentsOf: fixture))
        let peer = VoicePeer(factory: RTCPeerConnectionFactory(encoderFactory: nil, decoderFactory: nil, audioDevice: audio))
        let ready = expectation(description: "Voice ready")
        var started = false, transcript = "", lost = false
        var lastTranscriptAt = 0.0, maxPending = 0, rejected = 0
        peer.receive = { event in
            if event == .ready, !started { started = true; audio.beginSpeech(); ready.fulfill() }
            if event == .lost { lost = true }
            if case .transcript(let role, let text) = event, role == "You" {
                transcript += text; lastTranscriptAt = ProcessInfo.processInfo.systemUptime
            }
        }
        var sessionID: String?
        do {
            let offer = try await peer.offer()
            let voice = try await api.create(sdp: offer, codex: false, requestID: UUID().uuidString)
            sessionID = voice.session_id
            try await peer.answer(voice.sdp)
            await fulfillment(of: [ready], timeout: 20)
            let begin = ProcessInfo.processInfo.systemUptime
            var frame = FramePacket(header: FrameHeader(session_id: id, epoch: 1, frame_id: 0,
                timestamp_s: begin, tracking: "normal", camera_convention: "arkit",
                depth_width: 256, depth_height: 192, rgb_width: 0, rgb_height: 0, rgb_bytes: 0,
                fx: 200, fy: 200, cx: 128, cy: 96,
                camera_to_world: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]),
                depth: [Float](repeating: 2, count: 256 * 192),
                confidence: Data(repeating: 2, count: 256 * 192), jpeg: Data())
            for index in 0..<600 {
                frame.header.frame_id = index
                frame.header.timestamp_s = ProcessInfo.processInfo.systemUptime
                if !uploads.enqueue(try frame.encoded(), header: frame.header) { rejected += 1 }
                maxPending = max(maxPending, uploads.pending)
                if index % 50 == 0 {
                    print("VOICE_SOAK progress frame=\(index) pending=\(uploads.pending) stored=\(uploads.stored) bytes=\(uploads.bytesStored) input_chars=\(transcript.count)")
                }
                let remaining = begin + Double(index + 1) * 0.2 - ProcessInfo.processInfo.systemUptime
                if remaining > 0 { try await Task.sleep(for: .seconds(remaining)) }
            }
            let summary: [String: Any] = ["slow_receiver": slowReceiver, "duration_s": ProcessInfo.processInfo.systemUptime - begin,
                "video_dropped": uploads.dropped, "buffered_bytes": uploads.bufferedBytes,
                "max_pending": maxPending, "pending": uploads.pending, "rejected": rejected,
                "stored": uploads.stored, "bytes_stored": uploads.bytesStored, "lost": lost,
                "transcript_age_s": ProcessInfo.processInfo.systemUptime - lastTranscriptAt,
                "transcript": transcript]
            print("VOICE_SOAK_RESULT " + String(decoding: try JSONSerialization.data(withJSONObject: summary, options: [.sortedKeys]), as: UTF8.self))
            XCTAssertFalse(lost)
            XCTAssertGreaterThan(uploads.stored, 50)
            XCTAssertLessThan(ProcessInfo.processInfo.systemUptime - lastTranscriptAt, 15)
            peer.close()
            try await api.end(sessionID: voice.session_id)
            sessionID = nil
            try await Task.sleep(for: .milliseconds(300))
            let attachment = XCTAttachment(data: try Data(contentsOf: VoiceTrace.url), uniformTypeIdentifier: "public.json")
            attachment.name = "voice-soak-trace.jsonl"; attachment.lifetime = .keepAlways
            add(attachment)
        } catch {
            peer.close()
            if let sessionID { try? await api.end(sessionID: sessionID) }
            uploads.discard(); stream.disconnect()
            await close(room.id, base: rooms.base)
            throw error
        }
        uploads.discard(); stream.disconnect()
        await close(room.id, base: rooms.base)
    }

    private func close(_ room: String, base: URL) async {
        var request = URLRequest(url: base.appendingPathComponent("v1/rooms/\(room)/close"))
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
    }
}
