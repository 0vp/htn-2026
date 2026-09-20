import AVFoundation
import UIKit
import XCTest
@testable import HTNApp

private final class QueuedFixture: BufferedVoiceAudio, @unchecked Sendable {
    var captured: @Sendable (Data, Double) -> Void = { _, _ in }
    var failed: @Sendable (String) -> Void = { _ in }
    var outputLevel: @Sendable (Double) -> Void = { _ in }
    let pcm: Data
    var worker: Task<Void, Never>?
    init(_ pcm: Data) { self.pcm = pcm }
    func start() throws {
        worker = Task {
            let begin = ProcessInfo.processInfo.systemUptime
            var offset = 0
            while !Task.isCancelled {
                let bytes = offset < pcm.count ? Data(pcm[offset..<min(offset+9600,pcm.count)]) : Data(repeating: 0,count: 9600)
                captured(bytes, 0.2)
                offset += 9600
                let delay = begin + Double(offset)/48000 - ProcessInfo.processInfo.systemUptime
                if delay > 0 { try? await Task.sleep(for: .seconds(delay)) }
            }
        }
    }
    func stop() async { worker?.cancel(); await worker?.value; worker = nil }
    func mute(_ value: Bool) {}
    func play(_ pcm: Data) {}
}

final class ReliableVoiceTests: XCTestCase {
    @MainActor func testCompleteSpeechThroughDeployedQueue() async throws {
        guard let url = Bundle(for: Self.self).url(forResource: "voice", withExtension: "pcm") else {
            throw XCTSkip("Opt-in live test requires generated voice.pcm")
        }
        let source = try Data(contentsOf: url)
        var pcm = Data()
        for offset in stride(from: 0,to: source.count-1,by: 4) { pcm.append(source[offset..<offset+2]) }
        pcm.append(Data(repeating: 0,count: 48000*3))
        let audio = QueuedFixture(pcm + pcm)
        let rooms = RoomAPI(), device = "reliable-ios-\(UUID().uuidString)"
        let room = try await rooms.create(name: "Reliable iPhone speech test",device: device)
        let api = VoiceAPI(base: rooms.base, room: room.id, device: device)
        let peer = ReliableVoicePeer(api: api,audio: audio)
        let ready = expectation(description: "Reliable voice ready")
        let complete = expectation(description: "Two complete final utterances")
        var becameReady = false, finalized = false, transcript = ""
        peer.receive = { event in
            if event == .ready, !becameReady { becameReady = true; ready.fulfill() }
            if case .finalTranscript(let text) = event {
                transcript = text
                if text.lowercased().components(separatedBy: "green chair").count >= 3, !finalized {
                    finalized = true; complete.fulfill()
                }
            }
            if case .failure(let message) = event { XCTFail(message) }
        }
        do {
            let offer = try await peer.offer()
            let response = try await api.create(sdp: offer,codex: false,requestID: UUID().uuidString)
            try await peer.answer(response.sdp)
            await fulfillment(of: [ready],timeout: 25)
            await fulfillment(of: [complete],timeout: 60)
            let phrase = "Take the blue bottle from the wooden table and place it beside the green chair"
            XCTAssertEqual(SpeechAccuracy.errorRate(reference: phrase+" "+phrase,hypothesis: transcript),0)
            try await peer.finish()
            print("RELIABLE_IOS_RESULT ready=\(becameReady) finalized=\(finalized) transcript=\(transcript)")
        } catch { peer.close(); throw error }
        var request = URLRequest(url: rooms.base.appendingPathComponent("v1/rooms/\(room.id)/close"))
        request.httpMethod = "POST"
        _ = try await URLSession.shared.data(for: request)
    }

    @MainActor func testPhysicalMicrophoneCaptureContinuity() async throws {
        #if targetEnvironment(simulator)
        throw XCTSkip("Physical microphone check")
        #else
        final class Count: @unchecked Sendable {
            let lock = NSLock()
            var bytes = 0
            var outputPeak = 0.0
            var outputWindows = Set<Int>()
        }
        let idle = UIApplication.shared.isIdleTimerDisabled
        UIApplication.shared.isIdleTimerDisabled = true
        defer { UIApplication.shared.isIdleTimerDisabled = idle }
        let permission = await AVAudioApplication.requestRecordPermission()
        XCTAssertTrue(permission)
        print("RELIABLE_MIC_STATE foreground=\(UIApplication.shared.applicationState.rawValue) permission=\(AVAudioApplication.shared.recordPermission.rawValue)")
        let count = Count(), audio = BufferedAudioDevice()
        audio.captured = { pcm, _ in count.lock.withLock { count.bytes += pcm.count } }
        audio.failed = { message in XCTFail(message) }
        audio.outputLevel = { level in
            count.lock.withLock {
                count.outputPeak = max(count.outputPeak, level)
                if level > 0.01 {
                    count.outputWindows.insert(Int(ProcessInfo.processInfo.systemUptime / 2))
                }
            }
        }
        try audio.start()
        let begin = ProcessInfo.processInfo.systemUptime
        // Exercise the real output graph while input continues through voice processing.
        var tone = [Int16](repeating: 0, count: 12000)
        for index in tone.indices { tone[index] = Int16(sin(Double(index) * 2 * .pi * 440 / 24000) * 1300) }
        tone.withUnsafeBytes { audio.play(Data($0)) }
        try await Task.sleep(for: .seconds(2))
        print("RELIABLE_INITIAL_OUTPUT peak=\(count.lock.withLock { count.outputPeak })")
        tone.withUnsafeBytes { audio.play(Data($0)) }
        for _ in 0..<29 {
            try await Task.sleep(for: .seconds(2))
            tone.withUnsafeBytes { audio.play(Data($0)) }
        }
        print("RELIABLE_ENGINE \(audio.diagnostics)")
        await audio.stop()
        let duration = ProcessInfo.processInfo.systemUptime - begin
        let captured = count.lock.withLock { Double(count.bytes) / 48000 }
        print("RELIABLE_MIC_RESULT wall=\(duration) captured=\(captured)")
        XCTAssertGreaterThan(captured,59.5)
        XCTAssertEqual(AVAudioSession.sharedInstance().currentRoute.outputs.map(\.portType), [.builtInSpeaker])
        XCTAssertGreaterThan(count.lock.withLock { count.outputPeak },0.01)
        XCTAssertGreaterThanOrEqual(count.lock.withLock { count.outputWindows.count },25)
        XCTAssertLessThan(abs(captured-duration),0.5)
        #endif
    }
}
