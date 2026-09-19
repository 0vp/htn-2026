import XCTest
import WebRTC
@testable import HTNApp

/// Opt-in billed GCP test: serve known 48 kHz mono PCM16 at localhost:8810/voice.pcm.
final class VoiceSpeechTests: XCTestCase {
    @MainActor func testNativeMicrophonePacketsProduceRecognizedSpeech() async throws {
        var fixture = URLRequest(url: URL(string: "http://127.0.0.1:8810/voice.pcm")!)
        fixture.timeoutInterval = 1
        let pcm: Data
        do {
            let (data, response) = try await URLSession.shared.data(for: fixture)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.fileDoesNotExist) }
            pcm = data
        } catch { throw XCTSkip("Explicit PCM fixture server not running") }
        let (referenceData, referenceResponse) = try await URLSession.shared.data(from: URL(string: "http://127.0.0.1:8810/reference.txt")!)
        guard (referenceResponse as? HTTPURLResponse)?.statusCode == 200,
              let reference = String(data: referenceData, encoding: .utf8),
              let lastWord = SpeechAccuracy.words(reference).last else {
            XCTFail("Provide reference.txt with the exact fixture phrase"); return
        }
        let device = FixtureAudioDevice(pcm: pcm)
        let factory = RTCPeerConnectionFactory(encoderFactory: nil, decoderFactory: nil, audioDevice: device)
        let peer = VoicePeer(factory: factory)
        let rooms = RoomAPI()
        let id = "native-voice-\(UUID().uuidString)"
        let room = try await rooms.create(name: "Native voice diagnostic", device: id)
        let api = VoiceAPI(base: rooms.base, room: room.id, device: id)
        let recognized = expectation(description: "Known spoken phrase recognized")
        let replied = expectation(description: "Assistant replies to spoken phrase")
        let audible = expectation(description: "Incoming speech drives the mouth envelope")
        var userText = "", assistantText = ""
        var receivedInput = false, receivedOutput = false, receivedAudio = false
        let started = Date()
        peer.receive = { event in
            if event == .ready {
                print("Native voice ready seconds: \(Date().timeIntervalSince(started))")
                peer.mute(false); device.beginSpeech()
            }
            if case .level(let value) = event, value > 0.08, !receivedAudio {
                receivedAudio = true; audible.fulfill()
            }
            if case .transcript(let role, let text) = event {
                if role == "You" {
                    userText += text
                    if !receivedInput && SpeechAccuracy.words(userText).contains(lastWord) { receivedInput = true; recognized.fulfill() }
                } else {
                    assistantText += text
                    if !receivedOutput && !text.isEmpty { receivedOutput = true; replied.fulfill() }
                }
            }
        }
        defer { peer.receive = nil; peer.close() }
        let session = try await api.create(sdp: peer.offer(), codex: false, requestID: UUID().uuidString)
        do {
            try await peer.answer(session.sdp)
            await fulfillment(of: [recognized, replied, audible], timeout: 35)
            let errorRate = SpeechAccuracy.errorRate(reference: reference, hypothesis: userText)
            XCTAssertEqual(SpeechAccuracy.words(userText).first, SpeechAccuracy.words(reference).first, "Opening word must survive startup")
            XCTAssertLessThanOrEqual(errorRate, 0.10, "Full-phrase word error rate: \(errorRate); transcript: \(userText)")
            print("Word error rate: \(errorRate)")
            print("Native speech test seconds: \(Date().timeIntervalSince(started)); input: \(userText); reply: \(assistantText)")
            try await api.end(sessionID: session.session_id)
        } catch {
            try? await api.end(sessionID: session.session_id)
            throw error
        }
        var close = URLRequest(url: rooms.base.appendingPathComponent("v1/rooms/\(room.id)/close"))
        close.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: close)
    }
}
