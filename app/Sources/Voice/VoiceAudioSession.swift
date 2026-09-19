import AVFoundation
import WebRTC

/// WebRTC reapplies this configuration when its audio unit starts or restarts.
/// Setting AVAudioSession alone before that point loses the speaker preference.
enum VoiceAudioSession {
    static func configure() throws {
        let configuration = RTCAudioSessionConfiguration()
        configuration.category = AVAudioSession.Category.playAndRecord.rawValue
        configuration.mode = AVAudioSession.Mode.videoChat.rawValue
        configuration.categoryOptions = [.defaultToSpeaker, .allowBluetooth]
        RTCAudioSessionConfiguration.setWebRTC(configuration)
        let session = RTCAudioSession.sharedInstance()
        session.lockForConfiguration()
        defer { session.unlockForConfiguration() }
        try session.setConfiguration(configuration)
        // WebRTC owns activation/deactivation. Do not create another activation owner
        // or boost decoded PCM, which would increase clipping and speaker echo.
    }
}
