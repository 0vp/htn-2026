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
    // Construct the graph only after the recording session is active.
    private lazy var engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let inputSink = AVAudioSinkNode { _, _, _ in noErr }
    private let queue = DispatchQueue(label: "htn.voice.capture", qos: .userInitiated)
    private let lock = NSLock()
    private var queuedBytes = 0
    private var muted = false
    private var running = false
    private var tapped = false
    private var pending = Data()
    private var inputCallbacks = 0
    private var outputCallbacks = 0
    private var configurationObserver: NSObjectProtocol?
    private var awaitingInput = true
    private var playbackQueue: [(id: UUID, pcm: Data)] = []
    private var scheduled = Set<UUID>()
    private var playbackGeneration = 0
    private var routeObserver: NSObjectProtocol?
    private var playbackBytes = 0
    var diagnostics: String {
        let counts = lock.withLock { "inputCallbacks=\(inputCallbacks) outputCallbacks=\(outputCallbacks)" }
        let session = AVAudioSession.sharedInstance()
        let routes = session.currentRoute.outputs.map { $0.portType.rawValue }.joined(separator: ",")
        return "running=\(engine.isRunning) playing=\(player.isPlaying) \(counts) output=\(routes)"
    }
    private let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 24000,
                                      channels: 1, interleaved: false)!
    var captured: @Sendable (Data, Double) -> Void = { _, _ in }
    var failed: @Sendable (String) -> Void = { _ in }
    var outputLevel: @Sendable (Double) -> Void = { _ in }

    func start() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker])
        try session.setPreferredSampleRate(48000)
        try session.setPreferredIOBufferDuration(0.01)
        try session.setActive(true)
        try session.overrideOutputAudioPort(.speaker)
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(true)
        let source = input.outputFormat(forBus: 0)
        guard source.commonFormat == .pcmFormatFloat32, source.channelCount > 0, source.sampleRate > 0 else {
            throw APIError(message: "Microphone audio format is unavailable.")
        }
        guard let converter = AVAudioConverter(from: source, to: format) else {
            throw APIError(message: "Could not convert microphone audio.")
        }
        engine.attach(inputSink)
        engine.connect(input, to: inputSink, format: source)
        engine.attach(player)
        let playback = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1)!
        engine.connect(player, to: engine.mainMixerNode, format: playback)
        engine.connect(engine.mainMixerNode, to: engine.outputNode, format: nil)
        lock.lock(); running = true; tapped = true; lock.unlock()
        input.installTap(onBus: 0, bufferSize: 960, format: source) { [weak self] buffer, _ in
            self?.capture(buffer, converter: converter)
        }
        engine.mainMixerNode.installTap(onBus: 0, bufferSize: 960, format: nil) { [weak self] buffer, _ in
            self?.lock.withLock { self?.outputCallbacks += 1 }
            guard let samples = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return }
            var energy = 0.0
            for i in 0..<Int(buffer.frameLength) { energy += Double(samples[i] * samples[i]) }
            self?.outputLevel(min(1, sqrt(energy / Double(buffer.frameLength)) * 7))
        }
        configurationObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main
        ) { [weak self] _ in
            guard let self, self.lock.withLock({ self.running }), !self.engine.isRunning else { return }
            // iOS stops the engine when activating voice processing changes the
            // hardware format. Re-start the graph after it adopts that format.
            self.lock.withLock { self.awaitingInput = true }
            self.playbackGeneration += 1
            self.scheduled.removeAll()
            do { self.player.stop(); try self.engine.start(); self.player.play() }
            catch { self.failed("Audio route changed: " + error.localizedDescription) }
        }
        routeObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification, object: session, queue: .main
        ) { [weak self] _ in
            guard let self, self.lock.withLock({ self.running }),
                  session.currentRoute.outputs.contains(where: { $0.portType != .builtInSpeaker }) else { return }
            do { try session.overrideOutputAudioPort(.speaker) }
            catch { self.failed("Could not restore speakerphone: " + error.localizedDescription) }
        }
        engine.prepare(); try engine.start(); player.play()
    }
    private func capture(_ buffer: AVAudioPCMBuffer, converter: AVAudioConverter) {
        let size = Int(buffer.frameLength) * Int(buffer.format.channelCount) * 4
        lock.lock()
        inputCallbacks += 1
        let firstInput = awaitingInput
        awaitingInput = false
        let active = running, overflow = queuedBytes + size > 4_000_000
        if active && !overflow { queuedBytes += size }
        if overflow { running = false }
        lock.unlock()
        if firstInput && active {
            DispatchQueue.main.async { [weak self] in self?.schedulePlayback() }
        }
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
        guard playbackBytes + pcm.count <= 2_880_000 else {
            failed("Audio output is unavailable; playback buffer is full."); return
        }
        playbackQueue.append((UUID(), pcm)); playbackBytes += pcm.count
        schedulePlayback()
    }
    private func schedulePlayback() {
        guard lock.withLock({ running && !awaitingInput }), engine.isRunning else { return }
        let format = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1)!
        let generation = playbackGeneration
        for item in playbackQueue where !scheduled.contains(item.id) {
            guard let buffer = AVAudioPCMBuffer(pcmFormat: format,
                frameCapacity: AVAudioFrameCount(item.pcm.count / 2)) else {
                failed("Could not allocate audio playback buffer."); return
            }
            buffer.frameLength = buffer.frameCapacity
            item.pcm.withUnsafeBytes { raw in
                for (index, value) in raw.bindMemory(to: Int16.self).enumerated() {
                    buffer.floatChannelData![0][index] = Float(value) / 32768
                }
            }
            scheduled.insert(item.id)
            let id = item.id
            // Keep PCM until playback completes. A hardware-format reset clears
            // the player's schedule, so uncompleted buffers can be rescheduled.
            player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.playbackGeneration == generation, self.engine.isRunning,
                          let index = self.playbackQueue.firstIndex(where: { $0.id == id }) else { return }
                    self.playbackBytes -= self.playbackQueue[index].pcm.count
                    self.playbackQueue.remove(at: index)
                    self.scheduled.remove(id)
                }
            }
        }
    }
    func stop() async {
        let wasRunning = lock.withLock { let was = tapped; running = false; tapped = false; return was }
        if let configurationObserver { NotificationCenter.default.removeObserver(configurationObserver) }
        configurationObserver = nil
        if let routeObserver { NotificationCenter.default.removeObserver(routeObserver) }
        routeObserver = nil
        playbackGeneration += 1
        if wasRunning { engine.inputNode.removeTap(onBus: 0); engine.mainMixerNode.removeTap(onBus: 0) }
        engine.stop(); player.stop()
        playbackQueue.removeAll(); scheduled.removeAll(); playbackBytes = 0
        await withCheckedContinuation { continuation in
            queue.async { [self] in
                if !pending.isEmpty { captured(pending, 0); pending.removeAll() }
                continuation.resume()
            }
        }
    }
}
