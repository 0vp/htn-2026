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
        peer.receive?(.inputLevel(0))
        XCTAssertFalse(peer.muted, "Silence must never mute capture or gate the next word")
        peer.receive?(.inputLevel(0.4))
        XCTAssertEqual(model.microphoneLevel, 0.4)
        peer.receive?(.packets(120, 80))
        XCTAssertEqual(model.packetsSent, 120)
        XCTAssertEqual(model.packetsReceived, 80)
        peer.receive?(.level(0.7))
        XCTAssertEqual(model.mouth, 0.7)
        peer.receive?(.level(0))
        XCTAssertEqual(model.mouth, 0)
        peer.receive?(.recovering(true))
        XCTAssertEqual(model.status, "Reconnecting voice…")
        XCTAssertFalse(peer.muted, "Network recovery must not gate microphone capture")
        XCTAssertFalse(peer.closed)
        peer.receive?(.recovering(false))
        XCTAssertFalse(model.reconnecting)
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

    func testCaptionsDropSoundAnnotations() {
        XCTAssertEqual(Caption.spoken("Hello [tongue click] there"), "Hello there")
        XCTAssertEqual(Caption.spoken("(clicks tongue) okay *sighs* sure"), "okay sure")
        XCTAssertEqual(Caption.spoken("Turn [tongue"), "Turn", "Hide an annotation until it closes")
        XCTAssertEqual(Caption.spoken("click] left"), "left", "Drop an orphan left by trimming")
        XCTAssertEqual(Caption.spoken("  spaced   words "), "spaced words")
        XCTAssertEqual(Caption.spoken("Please (keep these words) and [these words]"), "Please (keep these words) and [these words]")
        XCTAssertEqual(Caption.spoken("The result is (twenty"), "The result is (twenty")
        XCTAssertEqual(Caption.spoken("Use *three* bottles"), "Use *three* bottles")
    }

    @MainActor func testSplitAnnotationNeverReachesCaptions() async throws {
        let peer = FakeVoicePeer()
        let model = VoiceModel(api: FakeVoiceAPI(), preferences: UserDefaults(suiteName: UUID().uuidString)!,
                               makePeer: { peer }, permission: { true })
        model.start()
        try await Task.sleep(for: .milliseconds(100))
        for delta in ["Move ", "[tongue ", "click]", " forward"] { peer.receive?(.transcript("You", delta)) }
        XCTAssertEqual(model.userTranscript, "Move forward")
        XCTAssertEqual(model.caption, "Move forward")
    }

    func testSpeechAccuracyDetectsMissingOpeningWords() {
        XCTAssertEqual(SpeechAccuracy.errorRate(reference: "Please bring the bottle", hypothesis: "Please bring the bottle."), 0)
        XCTAssertEqual(SpeechAccuracy.errorRate(reference: "Please bring the bottle", hypothesis: "bring the bottle"), 0.25)
    }

    func testSpeechMeterOpensAtOnceAndClosesSmoothly() {
        var meter = SpeechMeter()
        XCTAssertEqual(meter.update(.init(energy: 0, duration: 0, level: 0)), 0)
        // 40 ms slice at RMS 0.2: energy grows by 0.2^2 * 0.04.
        let open = meter.update(.init(energy: 0.0016, duration: 0.04, level: 0.01))
        XCTAssertGreaterThan(open, 0.9, "Uses this slice's loudness, not the slow average")
        let closing = meter.update(.init(energy: 0.0016, duration: 0.08, level: 0.2))
        XCTAssertLessThan(closing, open)
        XCTAssertGreaterThan(closing, 0, "Closes over a few frames instead of snapping shut")
        var shut = closing
        for step in 3...12 { shut = meter.update(.init(energy: 0.0016, duration: 0.04 * Double(step), level: 0)) }
        XCTAssertEqual(shut, 0)
    }
}
