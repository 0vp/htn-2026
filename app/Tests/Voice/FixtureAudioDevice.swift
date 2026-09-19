import Foundation
import WebRTC

/// Test-only PCM microphone. Dedicated thread satisfies WebRTC's audio callback affinity.
final class FixtureAudioDevice: NSObject, RTCAudioDevice {
    let deviceInputSampleRate: Double = 48000
    let deviceOutputSampleRate: Double = 48000
    let inputIOBufferDuration: TimeInterval = 0.01
    let outputIOBufferDuration: TimeInterval = 0.01
    let inputNumberOfChannels = 1
    let outputNumberOfChannels = 1
    let inputLatency: TimeInterval = 0
    let outputLatency: TimeInterval = 0
    private(set) var isInitialized = false
    let isPlayoutInitialized = true
    let isRecordingInitialized = true
    private(set) var isPlaying = false
    private(set) var isRecording = false
    private let lock = NSRecursiveLock()
    private var delegate: (any RTCAudioDeviceDelegate)?
    private var worker: Thread?
    private let pcm: Data
    private var speechEnabled = false

    init(pcm: Data) { self.pcm = pcm; super.init() }
    func beginSpeech() { lock.lock(); defer { lock.unlock() }; speechEnabled = true }
    func initialize(with delegate: any RTCAudioDeviceDelegate) -> Bool {
        lock.lock(); defer { lock.unlock() }
        self.delegate = delegate; isInitialized = true
        let worker = Thread { [weak self] in self?.pump() }
        worker.qualityOfService = .userInteractive
        self.worker = worker; worker.start()
        return true
    }
    func terminateDevice() -> Bool {
        lock.lock(); defer { lock.unlock() }
        worker?.cancel(); worker = nil; delegate = nil; isInitialized = false
        return true
    }
    func initializePlayout() -> Bool { true }
    func initializeRecording() -> Bool { true }
    func startPlayout() -> Bool { lock.lock(); defer { lock.unlock() }; isPlaying = true; return true }
    func stopPlayout() -> Bool { lock.lock(); defer { lock.unlock() }; isPlaying = false; return true }
    func startRecording() -> Bool { lock.lock(); defer { lock.unlock() }; isRecording = true; return true }
    func stopRecording() -> Bool { lock.lock(); defer { lock.unlock() }; isRecording = false; return true }

    private func pump() {
        var offset = 0
        var tick = 0
        var nextTick = ProcessInfo.processInfo.systemUptime
        while !Thread.current.isCancelled {
            lock.lock()
            if let delegate {
                var flags = AudioUnitRenderActionFlags()
                var timestamp = AudioTimeStamp()
                timestamp.mSampleTime = Double(tick * 480)
                timestamp.mFlags = .sampleTimeValid
                var samples = [Int16](repeating: 0, count: 480)
                samples.withUnsafeMutableBytes { buffer in
                    var list = AudioBufferList(mNumberBuffers: 1,
                        mBuffers: AudioBuffer(mNumberChannels: 1, mDataByteSize: 960, mData: buffer.baseAddress))
                    if isPlaying { _ = delegate.getPlayoutData(&flags, &timestamp, 0, 480, &list) }
                    if isRecording {
                        buffer.initializeMemory(as: UInt8.self, repeating: 0)
                        // Repeat a known phrase, separated by silence, after transport setup.
                        let cycle = pcm.count + 48000 * 2 * 3
                        if speechEnabled && offset < pcm.count {
                            let count = min(960, pcm.count - offset)
                            pcm.copyBytes(to: buffer.bindMemory(to: UInt8.self), from: offset..<(offset + count))
                        }
                        if speechEnabled { offset = (offset + 960) % cycle }
                        _ = delegate.deliverRecordedData(&flags, &timestamp, 0, 480, &list, nil, nil)
                    }
                }
            }
            lock.unlock()
            tick += 1
            // Absolute deadlines include callback work; sleeping 10 ms *after* that
            // work slowed the fixture and starved transport on a physical phone.
            nextTick += 0.01
            let remaining = nextTick - ProcessInfo.processInfo.systemUptime
            if remaining > 0 { Thread.sleep(forTimeInterval: remaining) }
        }
    }
}
