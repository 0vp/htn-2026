import XCTest
@testable import HTNApp

final class VoiceConnectionRecoveryTests: XCTestCase {
    @MainActor func testBriefOutageRecoversWithoutEndingCall() async throws {
        let recovery = VoiceConnectionRecovery(grace: .milliseconds(60))
        var ended = false
        XCTAssertTrue(recovery.begin { ended = true })
        recovery.cancel()
        try await Task.sleep(for: .milliseconds(90))
        XCTAssertFalse(ended)
    }

    @MainActor func testRepeatedDisconnectDoesNotExtendDeadline() async throws {
        let recovery = VoiceConnectionRecovery(grace: .milliseconds(60))
        var ended = 0
        XCTAssertTrue(recovery.begin { ended += 1 })
        XCTAssertFalse(recovery.begin { ended += 100 })
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(ended, 1)
    }
}
