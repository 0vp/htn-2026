import XCTest
@testable import HTNApp

final class VoiceHealthTests: XCTestCase {
    func testSilentSamplesAreStillCaptureProgress() {
        var health = VoiceHealth()
        _ = health.capture(duration: 0, now: 0, muted: false)
        XCTAssertEqual(health.capture(duration: 3, now: 3, muted: false), "Capture samples advancing")
        XCTAssertEqual(health.capture(duration: 3, now: 6, muted: false), "Capture counter stalled")
        XCTAssertEqual(health.capture(duration: 4, now: 7, muted: false), "Capture samples advancing")
    }

    func testUnavailableMutedAndResetCountersAreNotStalls() {
        var health = VoiceHealth()
        _ = health.capture(duration: 10, now: 0, muted: false)
        XCTAssertEqual(health.capture(duration: nil, now: 9, muted: false), "Capture measurement unavailable")
        XCTAssertEqual(health.capture(duration: 10, now: 10, muted: true), "Mic muted")
        XCTAssertEqual(health.capture(duration: 10, now: 11, muted: false), "Measuring capture progress")
        XCTAssertEqual(health.capture(duration: 0, now: 12, muted: false), "Measuring capture progress")
    }
}
