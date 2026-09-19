import AVFoundation
import WebRTC
import XCTest
@testable import HTNApp

final class VoiceAudioSessionTests: XCTestCase {
    func testSpeakerPreferenceSurvivesWebRTCAudioStartup() throws {
        try VoiceAudioSession.configure()
        let session = RTCAudioSession.sharedInstance()
        session.lockForConfiguration()
        defer { session.unlockForConfiguration() }
        // Model WebRTC's later reapplication, which previously removed defaultToSpeaker.
        try session.setCategory(.playAndRecord, with: [.allowBluetooth])
        try session.setMode(.voiceChat)
        let startup = RTCAudioSessionConfiguration.webRTC()
        XCTAssertTrue(startup.categoryOptions.contains(.defaultToSpeaker))
        XCTAssertEqual(startup.mode, AVAudioSession.Mode.videoChat.rawValue)
        try session.setConfiguration(startup)
        XCTAssertTrue(AVAudioSession.sharedInstance().categoryOptions.contains(.defaultToSpeaker))
        XCTAssertEqual(AVAudioSession.sharedInstance().mode, .videoChat)
    }
}
