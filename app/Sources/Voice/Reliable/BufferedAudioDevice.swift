import AVFoundation

protocol BufferedVoiceAudio: AnyObject {
    var captured: @Sendable (Data, Double) -> Void { get set }
    var failed: @Sendable (String) -> Void { get set }
    var outputLevel: @Sendable (Double) -> Void { get set }
    func start() throws
    func mute(_ value: Bool)
    func play(_ pcm: Data)
    func stop() async
}

/// One voice-processing audio engine owns input and output (echo cancellation).
/// Conversion and disk writes run on a dedicated queue, independently of uploads/UI.
final class BufferedAudioDevice: BufferedVoiceAudio, @unchecked Sendable {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let queue = DispatchQueue(label: "htn.voice.capture", qos: .userInitiated)
    private let lock = NSLock()
    private var queuedBytes = 0
    private var muted = false
    private var running = false
    private var tapped = false
    private var pending = Data()
    private let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 24000,
                                      channels: 1, interleaved: false)!
    var captured: @Sendable (Data, Double) -> Void = { _, _ in }
    var failed: @Sendable (String) -> Void = { _ in }
    var outputLevel: @Sendable (Double) -> Void = { _ in }

    func start() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
        try session.setActive(true)
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(true)
        let source = input.outputFormat(forBus: 0)
        guard source.commonFormat == .pcmFormatFloat32, source.channelCount > 0, source.sampleRate > 0 else {
            throw APIError(message: "Microphone audio format is unavailable.")
        }
        guard let converter = AVAudioConverter(from: source, to: format) else {
            throw APIError(message: "Could not convert microphone audio.")
        }
        engine.attach(player)
        let playback = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1)!
        engine.connect(player, to: engine.mainMixerNode, format: playback)
        lock.lock(); running = true; tapped = true; lock.unlock()
        input.installTap(onBus: 0, bufferSize: 960, format: source) { [weak self] buffer, _ in
            self?.capture(buffer, converter: converter)
        }
        engine.mainMixerNode.installTap(onBus: 0, bufferSize: 960, format: nil) { [weak self] buffer, _ in
            guard let samples = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return }
            var energy = 0.0
            for i in 0..<Int(buffer.frameLength) { energy += Double(samples[i] * samples[i]) }
            self?.outputLevel(min(1, sqrt(energy / Double(buffer.frameLength)) * 7))
        }
        engine.prepare(); try engine.start(); player.play()
    }
    private func capture(_ buffer: AVAudioPCMBuffer, converter: AVAudioConverter) {
        let size = Int(buffer.frameLength) * Int(buffer.format.channelCount) * 4
        lock.lock()
        let active = running, overflow = queuedBytes + size > 4_000_000
        if active && !overflow { queuedBytes += size }
        if overflow { running = false }
        lock.unlock()
        guard active && !overflow else {
            if active { failed("Audio capture worker fell behind. Pending audio retained.") }
            return
        }
        guard let copy = AVAudioPCMBuffer(pcmFormat: buffer.format, frameCapacity: buffer.frameLength) else {
            lock.withLock { queuedBytes -= size }
            failed("Could not buffer microphone audio. Recording must stop.")
            return
        }
        copy.frameLength = buffer.frameLength
        for channel in 0..<Int(buffer.format.channelCount) {
            memcpy(copy.floatChannelData![channel], buffer.floatChannelData![channel], Int(buffer.frameLength) * 4)
        }
        queue.async { [weak self] in
            guard let self else { return }
            defer { self.lock.lock(); self.queuedBytes -= size; self.lock.unlock() }
            let capacity = AVAudioFrameCount(Double(copy.frameLength) * 24000 / copy.format.sampleRate + 32)
            guard let output = AVAudioPCMBuffer(pcmFormat: self.format, frameCapacity: capacity) else {
                self.failed("Could not allocate the audio conversion buffer."); return
            }
            var supplied = false
            var error: NSError?
            converter.convert(to: output, error: &error) { _, status in
                if supplied { status.pointee = .noDataNow; return nil }
                supplied = true; status.pointee = .haveData; return copy
            }
            if let error { self.failed(error.localizedDescription); return }
            let count = Int(output.frameLength)
            guard count > 0, let samples = output.int16ChannelData?[0] else { return }
            self.lock.lock(); let muted = self.muted; self.lock.unlock()
            let data = muted ? Data(repeating: 0, count: count * 2) : Data(bytes: samples, count: count * 2)
            self.pending.append(data)
            while self.pending.count >= 9600 {
                let chunk = Data(self.pending.prefix(9600)); self.pending.removeFirst(9600)
                let energy = chunk.withUnsafeBytes { raw -> Double in
                    let values = raw.bindMemory(to: Int16.self)
                    return sqrt(values.reduce(0.0) { $0 + pow(Double($1) / 32768, 2) } / Double(values.count))
                }
                self.captured(chunk, min(1, energy * 7))
            }
        }
    }
    func mute(_ value: Bool) { lock.lock(); muted = value; lock.unlock() }
    func play(_ pcm: Data) {
        guard lock.withLock({ running }) else { return }
        guard pcm.count % 2 == 0, !pcm.isEmpty else { return }
        let format = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1)!
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(pcm.count / 2)) else { return }
        buffer.frameLength = buffer.frameCapacity
        pcm.withUnsafeBytes { raw in
            for (index, value) in raw.bindMemory(to: Int16.self).enumerated() {
                let sample = Float(value) / 32768
                buffer.floatChannelData![0][index] = sample
            }
        }
        player.scheduleBuffer(buffer)
    }
    func stop() async {
        let wasRunning = lock.withLock { let was = tapped; running = false; tapped = false; return was }
        if wasRunning { engine.inputNode.removeTap(onBus: 0); engine.mainMixerNode.removeTap(onBus: 0) }
        engine.stop(); player.stop()
        await withCheckedContinuation { continuation in
            queue.async { [self] in
                if !pending.isEmpty { captured(pending, 0); pending.removeAll() }
                continuation.resume()
            }
        }
    }
}
