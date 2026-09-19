import AVFoundation
import Foundation

/// Bounded, local metadata only: no audio, transcripts, SDP, credentials or room IDs.
final class VoiceTrace {
    private static let queue = DispatchQueue(label: "htn.voice.trace", qos: .utility)
    private var handle: FileHandle?
    private var lines = 0
    private var observers: [NSObjectProtocol] = []
    static var url: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("voice-diagnostics.jsonl")
    }

    init() {
        Self.queue.async { [self] in
            FileManager.default.createFile(atPath: Self.url.path, contents: nil)
            handle = try? FileHandle(forWritingTo: Self.url)
        }
        for name in [AVAudioSession.routeChangeNotification, AVAudioSession.interruptionNotification,
                     AVAudioSession.mediaServicesWereLostNotification, AVAudioSession.mediaServicesWereResetNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: nil) { [weak self] note in
                let reason = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? NSNumber
                let interruption = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? NSNumber
                self?.write(["event": name.rawValue, "reason": reason ?? -1,
                             "interruption": interruption ?? -1])
            })
        }
        write(["event": "capture_setup"])
    }

    func write(_ fields: [String: Any]) {
        let audio = AVAudioSession.sharedInstance()
        var row = fields
        row["time"] = Date().timeIntervalSince1970
        row["input"] = audio.currentRoute.inputs.map { $0.portType.rawValue }
        row["sample_rate"] = audio.sampleRate
        row["input_available"] = audio.isInputAvailable
        row["mode"] = audio.mode.rawValue
        row["thermal"] = ProcessInfo.processInfo.thermalState.rawValue
        guard var bytes = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) else { return }
        bytes.append(10)
        let data = bytes
        Self.queue.async { [self] in
            guard lines < 2000 else { return }
            try? handle?.write(contentsOf: data)
            lines += 1
        }
    }

    func stop() {
        observers.forEach { NotificationCenter.default.removeObserver($0) }
        observers.removeAll()
        write(["event": "capture_closed"])
        Self.queue.async { [self] in try? handle?.close(); handle = nil }
    }
}
