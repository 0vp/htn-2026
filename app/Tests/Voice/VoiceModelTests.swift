import XCTest
@testable import HTNApp

@MainActor private final class FakeVoiceAPI: VoiceServing {
    var enabled: [Bool] = []
    var ended: [String] = []
    var codex = true
    var echo: Bool?
    var delay: UInt64 = 0
    func capabilities() async throws -> VoiceCapabilities { .init(available: true, codex_available: codex) }
    func create(sdp: String, codex: Bool, requestID: String) async throws -> VoiceSession {
        if delay > 0 { try await Task.sleep(nanoseconds: delay) }
        enabled.append(codex)
        return .init(session_id: "live_test", sdp: "answer", codex_enabled: echo ?? codex)
    }
    func end(sessionID: String) async throws { ended.append(sessionID) }
}
@MainActor private final class FakeVoicePeer: VoiceTransport {
    var receive: ((VoiceEvent) -> Void)?
    var muted = true
    var closed = false
    func offer() async throws -> String { "offer" }
    func answer(_ sdp: String) async throws { receive?(.ready) }
    func mute(_ muted: Bool) { self.muted = muted }
    func close() { closed = true }
}

final class VoiceModelTests: XCTestCase {
    @MainActor func testDefaultCodexAndAudioDrivesFace() async throws {
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let api = FakeVoiceAPI(), peer = FakeVoicePeer()
        let model = VoiceModel(api: api, preferences: defaults, makePeer: { peer }, permission: { true })
        XCTAssertTrue(model.codexEnabled)
        model.start()
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(api.enabled, [true])
        XCTAssertEqual(model.phase, .listening)
        peer.receive?(.transcript("Assistant", "Hello"))
        XCTAssertEqual(model.mouth, 0, "Text must not drive mouth animation")
        peer.receive?(.transcript("You", "Hi"))
        peer.receive?(.transcript("Assistant", " there"))
        peer.receive?(.transcript("You", " again"))
        XCTAssertEqual(model.userTranscript, "Hi again")
        XCTAssertEqual(model.assistantTranscript, "Hello there")
        peer.receive?(.inputLevel(0.4))
        XCTAssertEqual(model.microphoneLevel, 0.4)
        peer.receive?(.packets(120, 80))
        XCTAssertEqual(model.packetsSent, 120)
        XCTAssertEqual(model.packetsReceived, 80)
        peer.receive?(.level(0.7))
        XCTAssertEqual(model.mouth, 0.7)
        peer.receive?(.level(0))
        XCTAssertEqual(model.mouth, 0)
        model.setMuted(true)
        XCTAssertTrue(peer.muted)
        XCTAssertEqual(model.microphoneLevel, 0)
        await model.setCodex(false)
        XCTAssertTrue(peer.closed)
        XCTAssertEqual(api.ended, ["live_test"])
        XCTAssertFalse(model.codexEnabled)
        XCTAssertEqual(model.phase, .idle)
        let restored = VoiceModel(api: api, preferences: defaults, makePeer: { peer }, permission: { true })
        XCTAssertFalse(restored.codexEnabled)
    }
    @MainActor func testRejectsModeMismatchAndUnavailableCodex() async throws {
        let api = FakeVoiceAPI(), peer = FakeVoicePeer()
        api.echo = false
        let model = VoiceModel(api: api, preferences: UserDefaults(suiteName: UUID().uuidString)!,
                               makePeer: { peer }, permission: { true })
        model.start()
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(model.phase, .failed)
        XCTAssertTrue(peer.closed)
        XCTAssertEqual(api.ended, ["live_test"])
        api.codex = false
        model.start()
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(api.enabled.count, 1)
        XCTAssertTrue(model.error?.contains("Turn off") == true)
    }
    @MainActor func testEndingDuringCreationCleansLateSession() async throws {
        let api = FakeVoiceAPI(), peer = FakeVoicePeer()
        api.delay = 120_000_000
        let model = VoiceModel(api: api, preferences: UserDefaults(suiteName: UUID().uuidString)!,
                               makePeer: { peer }, permission: { true })
        model.start()
        try await Task.sleep(for: .milliseconds(30))
        let lateCallback = peer.receive
        await model.end()
        lateCallback?(.ready)
        try await Task.sleep(for: .milliseconds(160))
        XCTAssertEqual(model.phase, .idle)
        XCTAssertEqual(api.ended, ["live_test"])
        XCTAssertTrue(peer.closed)
    }
    func testEventDecodingIsBoundedToLiveProtocol() {
        XCTAssertEqual(VoiceEvent.decode(Data(#"{"type":"session.started"}"#.utf8)), .ready)
        XCTAssertEqual(VoiceEvent.decode(Data(#"{"type":"session.output_transcript.delta","delta":"hello"}"#.utf8)), .transcript("Assistant", "hello"))
        XCTAssertNil(VoiceEvent.decode(Data(#"{"type":"response.audio.delta","delta":"ignore"}"#.utf8)))
        XCTAssertNil(VoiceEvent.decode(Data("broken".utf8)))
    }
}
