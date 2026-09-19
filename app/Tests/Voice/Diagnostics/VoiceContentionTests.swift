import XCTest
import WebRTC
@testable import HTNApp

/// Opt-in physical-phone comparison. Supply generated 48 kHz mono PCM16 as a
/// test-bundle resource named voice.pcm. This exercises transport, not the mic DSP.
final class VoiceContentionTests: XCTestCase {
    @MainActor func testScanUploadContention() async throws {
        #if targetEnvironment(simulator)
        throw XCTSkip("Requires physical LiDAR iPhone")
        #else
        guard let url = Bundle(for: Self.self).url(forResource: "voice", withExtension: "pcm") else {
            throw XCTSkip("No explicit speech fixture supplied")
        }
        let pcm = try Data(contentsOf: url)
        for (index, scanning) in [false, true, true, false].enumerated() {
            try await run(pcm: pcm, scanning: scanning, index: index)
        }
        #endif
    }

    @MainActor private func run(pcm: Data, scanning: Bool, index: Int) async throws {
        let rooms = RoomAPI()
        let deviceID = "contention-\(UUID().uuidString)"
        let room = try await rooms.create(name: "Voice contention diagnostic", device: deviceID)
        let api = VoiceAPI(base: rooms.base, room: room.id, device: deviceID)
        let scan = ScanModel(room: room, device: deviceID)
        let audio = FixtureAudioDevice(pcm: pcm)
        let factory = RTCPeerConnectionFactory(encoderFactory: nil, decoderFactory: nil, audioDevice: audio)
        let peer = VoicePeer(factory: factory)
        let ready = expectation(description: "Voice ready")
        var started = false
        var transcript = ""
        peer.receive = { event in
            if event == .ready, !started {
                started = true; audio.beginSpeech(); ready.fulfill()
            }
            if case .transcript(let role, let text) = event, role == "You" { transcript += text }
        }
        var sessionID: String?
        do {
            if scanning { await scan.start() }
            let offer = try await peer.offer()
            let session = try await api.create(sdp: offer, codex: false, requestID: UUID().uuidString)
            sessionID = session.session_id
            try await peer.answer(session.sdp)
            await fulfillment(of: [ready], timeout: 20)
            try await Task.sleep(for: .seconds(25))
            scan.pause()
            let metadata: [String: Any] = ["trial": index, "scanning": scanning,
                "frames_captured": scan.captured, "frames_stored": scan.uploads.stored,
                "bytes_stored": scan.uploads.bytesStored, "tracking": scan.tracking,
                "scan_error": scan.error ?? "", "transcript": transcript]
            let result = try JSONSerialization.data(withJSONObject: metadata, options: [.sortedKeys])
            print("VOICE_COMPARISON \(String(decoding: result, as: UTF8.self))")
            if scanning { XCTAssertGreaterThan(scan.uploads.stored, 0, "Scan-on trial must actually upload frames") }
            XCTAssertFalse(transcript.isEmpty, "No speech transcript received")
            peer.close()
            try await api.end(sessionID: session.session_id)
            sessionID = nil
            try await Task.sleep(for: .milliseconds(300))
            let attachment = XCTAttachment(data: try Data(contentsOf: VoiceTrace.url), uniformTypeIdentifier: "public.json")
            attachment.name = "voice-trial-\(index)-scan-\(scanning).jsonl"
            attachment.lifetime = .keepAlways
            add(attachment)
        } catch {
            peer.close()
            if let sessionID { try? await api.end(sessionID: sessionID) }
            scan.finish()
            await close(room: room.id, base: rooms.base)
            throw error
        }
        scan.finish()
        await close(room: room.id, base: rooms.base)
    }

    private func close(room: String, base: URL) async {
        var request = URLRequest(url: base.appendingPathComponent("v1/rooms/\(room)/close"))
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
    }
}
