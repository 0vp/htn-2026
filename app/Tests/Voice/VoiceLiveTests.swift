import XCTest
@testable import HTNApp

/// Opt-in: run a credentialed local backend on port 8807. Creates a short billed voice session.
final class VoiceLiveTests: XCTestCase {
    @MainActor func testRealWebRTCSessionStartsAndHangsUp() async throws {
        let base = URL(string: "http://127.0.0.1:8807")!
        var probe = URLRequest(url: base.appendingPathComponent("health")); probe.timeoutInterval = 1
        do { _ = try await URLSession.shared.data(for: probe) }
        catch { throw XCTSkip("Live voice backend not running on port 8807") }
        let roomAPI = RoomAPI(base: base)
        let device = "voice-test-\(UUID().uuidString)"
        let room = try await roomAPI.create(name: "Voice transport test", device: device)
        let api = VoiceAPI(base: base, room: room.id, device: device)
        let peer = VoicePeer()
        let ready = expectation(description: "OpenAI session.started over native WebRTC")
        peer.receive = { event in if event == .ready { ready.fulfill() } }
        defer { peer.close() }
        let offer = try await peer.offer()
        let session = try await api.create(sdp: offer, codex: false, requestID: UUID().uuidString)
        do {
            XCTAssertFalse(session.codex_enabled)
            try await peer.answer(session.sdp)
            await fulfillment(of: [ready], timeout: 20)
            peer.mute(true)
            try await api.end(sessionID: session.session_id)
        } catch {
            try? await api.end(sessionID: session.session_id)
            throw error
        }
    }
}
