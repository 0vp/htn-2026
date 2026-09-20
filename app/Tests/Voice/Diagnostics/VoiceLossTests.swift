import XCTest
import WebRTC
@testable import HTNApp

/// Opt-in billed test: localhost:8810 speech fixture and localhost:8811 loss proxy.
final class VoiceLossTests: XCTestCase {
    @MainActor func testControlledAudioLoss() async throws {
        var probe = URLRequest(url: URL(string: "http://127.0.0.1:8811/stats")!)
        probe.timeoutInterval = 1
        do { _ = try await URLSession.shared.data(for: probe) }
        catch { throw XCTSkip("Loss proxy not running") }
        let (pcm, _) = try await URLSession.shared.data(from: URL(string: "http://127.0.0.1:8810/voice.pcm")!)
        let (reference, _) = try await URLSession.shared.data(from: URL(string: "http://127.0.0.1:8810/reference.txt")!)
        for profile in ["clean", "isolated", "burst"] {
            try await run(pcm: pcm, reference: String(decoding: reference, as: UTF8.self), profile: profile)
        }
    }

    @MainActor private func run(pcm: Data, reference: String, profile: String) async throws {
        let rooms = RoomAPI()
        let id = "loss-\(UUID().uuidString)"
        let room = try await rooms.create(name: "Voice loss diagnostic", device: id)
        let api = VoiceAPI(base: rooms.base, room: room.id, device: id)
        // One utterance then silence; do not hide a failed first utterance with a retry.
        let audio = FixtureAudioDevice(pcm: pcm + Data(repeating: 0, count: 48000 * 2 * 20))
        let peer = VoicePeer(factory: RTCPeerConnectionFactory(encoderFactory: nil, decoderFactory: nil, audioDevice: audio))
        let ready = expectation(description: "Session ready through loss relay")
        var transcript = "", started = false, lost = false
        peer.receive = { event in
            if event == .ready, !started { started = true; audio.beginSpeech(); ready.fulfill() }
            if event == .lost { lost = true }
            if case .transcript(let role, let text) = event, role == "You" { transcript += text }
        }
        var sessionID: String?
        do {
            let offer = try await peer.offer()
            let session = try await api.create(sdp: offer, codex: false, requestID: UUID().uuidString)
            sessionID = session.session_id
            var request = URLRequest(url: URL(string: "http://127.0.0.1:8811/configure")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["sdp": session.sdp, "profile": profile])
            let (data, _) = try await URLSession.shared.data(for: request)
            let answer = try JSONDecoder().decode([String: String].self, from: data)
            try await peer.answer(XCTUnwrap(answer["sdp"]))
            await fulfillment(of: [ready], timeout: 20)
            try await Task.sleep(for: .seconds(8))
            let (stats, _) = try await URLSession.shared.data(from: URL(string: "http://127.0.0.1:8811/stats")!)
            print("VOICE_LOSS \(profile) stats=\(String(decoding: stats, as: UTF8.self)) wer=\(SpeechAccuracy.errorRate(reference: reference, hypothesis: transcript)) transcript=\(transcript)")
            let counters = try JSONSerialization.jsonObject(with: stats) as! [String: Any]
            XCTAssertGreaterThan(counters["packets"] as? Int ?? 0, 250, "Audio must use the relay, not bypass it")
            if profile != "clean" { XCTAssertGreaterThan(counters["dropped"] as? Int ?? 0, 0) }
            XCTAssertFalse(lost, "Media loss must not tear down the call")
            peer.close()
            try await api.end(sessionID: session.session_id)
            sessionID = nil
        } catch {
            peer.close()
            if let sessionID { try? await api.end(sessionID: sessionID) }
            await close(room: room.id, base: rooms.base)
            throw error
        }
        await close(room: room.id, base: rooms.base)
    }

    private func close(room: String, base: URL) async {
        var request = URLRequest(url: base.appendingPathComponent("v1/rooms/\(room)/close"))
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
    }
}
