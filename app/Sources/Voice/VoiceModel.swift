import AVFoundation
import Combine
import Foundation

@MainActor
final class VoiceModel: ObservableObject {
    enum Phase: Equatable { case idle, connecting, listening, ending, failed }
    @Published private(set) var phase: Phase = .idle
    @Published private(set) var error: String?
    @Published private(set) var muted = false
    @Published private(set) var mouth: Double = 0
    @Published private(set) var caption = ""
    @Published private(set) var speaker = ""
    @Published private(set) var userTranscript = ""
    @Published private(set) var assistantTranscript = ""
    @Published private(set) var microphoneLevel: Double = 0
    @Published private(set) var audioDiagnostic = "Waiting for capture measurements…"
    @Published private(set) var packetsSent = 0
    @Published private(set) var packetsReceived = 0
    @Published private(set) var connectionDetail = "Connecting voice…"
    @Published private(set) var codexEnabled: Bool
    private let api: any VoiceServing
    private let makePeer: @MainActor () -> any VoiceTransport
    private let permission: () async -> Bool
    private let preferences: UserDefaults
    private var peer: (any VoiceTransport)?
    private var sessionID: String?
    private var generation = UUID()
    private var watchdog: Task<Void, Never>?
    private var startTask: Task<Void, Never>?
    private var interruption: AnyCancellable?
    // Raw transcript deltas; the published captions are these with sound annotations removed.
    private var rawUser = "", rawAssistant = "", rawCaption = ""
    var active: Bool { phase == .connecting || phase == .listening }
    var status: String {
        switch phase {
        case .idle: return "Ready to talk"
        case .connecting: return connectionDetail
        case .ending: return "Ending conversation…"
        case .failed: return "Voice unavailable"
        case .listening: return muted ? "Microphone muted" : (mouth > 0.08 ? "Speaking" : "Listening")
        }
    }

    init(api: any VoiceServing, preferences: UserDefaults = .standard,
         makePeer: @escaping @MainActor () -> any VoiceTransport = { VoicePeer() },
         permission: @escaping () async -> Bool = { await AVAudioApplication.requestRecordPermission() }) {
        self.api = api; self.preferences = preferences; self.makePeer = makePeer; self.permission = permission
        codexEnabled = preferences.object(forKey: "voiceCodexEnabled") as? Bool ?? true
        interruption = NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)
            .sink { [weak self] notification in
                guard let value = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                      value == AVAudioSession.InterruptionType.began.rawValue else { return }
                Task { @MainActor in await self?.end() }
            }
    }
    func setCodex(_ enabled: Bool) async {
        guard enabled != codexEnabled else { return }
        await end()
        codexEnabled = enabled
        preferences.set(enabled, forKey: "voiceCodexEnabled")
        // Explicit new Talk gesture starts a new session under the changed policy.
    }
    func start() {
        guard !active, phase != .ending else { return }
        let token = UUID(); generation = token
        phase = .connecting; error = nil; caption = ""; speaker = ""; mouth = 0; muted = false
        userTranscript = ""; assistantTranscript = ""; microphoneLevel = 0
        rawUser = ""; rawAssistant = ""; rawCaption = ""
        audioDiagnostic = "Waiting for capture measurements…"
        packetsSent = 0; packetsReceived = 0; connectionDetail = "Checking voice service…"
        startTask = Task { await connect(token) }
    }
    private func connect(_ token: UUID) async {
        do {
            let capability = try await api.capabilities()
            try validate(token)
            guard capability.available else { throw APIError(message: "Voice is not configured on the server yet.") }
            guard !codexEnabled || capability.codex_available else {
                throw APIError(message: "Codex is not connected yet. Turn off Connect to Codex to test conversation only.")
            }
            connectionDetail = "Checking microphone access…"
            guard await permission() else { throw APIError(message: "Allow microphone access for HTN in Settings to talk.") }
            try validate(token)
            let peer = makePeer(); self.peer = peer
            peer.receive = { [weak self] event in
                guard let self, self.generation == token else { return }
                self.handle(event)
            }
            connectionDetail = "Preparing audio connection…"
            let sdp = try await peer.offer()
            try validate(token)
            let mode = codexEnabled
            connectionDetail = "Starting GPT-Live…"
            let creation = Task { try await api.create(sdp: sdp, codex: mode, requestID: token.uuidString) }
            let result = try await creation.value
            // Even a late success must be hung up so it cannot leave a billed session behind.
            if generation != token || Task.isCancelled {
                _ = try? await Task { try await api.end(sessionID: result.session_id) }.value
                return
            }
            sessionID = result.session_id
            guard result.codex_enabled == codexEnabled else {
                throw APIError(message: "The server did not apply the requested Codex mode. Voice was stopped.")
            }
            connectionDetail = "Connecting audio…"
            try await peer.answer(result.sdp)
            if phase == .connecting {
                watchdog = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(15))
                    guard !Task.isCancelled, let self, self.generation == token, self.phase == .connecting else { return }
                    await self.fail("The voice session did not start. Try again.")
                }
            }
        } catch {
            guard generation == token, !Task.isCancelled else { return }
            await fail(error.localizedDescription)
        }
    }
    private func validate(_ token: UUID) throws {
        try Task.checkCancellation()
        guard generation == token else { throw CancellationError() }
    }
    func setMuted(_ value: Bool) {
        muted = value
        if value { microphoneLevel = 0 }
        peer?.mute(value || phase != .listening)
    }
    func end() async {
        guard phase != .ending else { return }
        generation = UUID()
        startTask?.cancel(); startTask = nil
        watchdog?.cancel(); watchdog = nil
        peer?.receive = nil; peer?.close(); peer = nil
        mouth = 0; microphoneLevel = 0
        let id = sessionID; sessionID = nil
        phase = .ending
        if let id {
            do { try await Task { try await api.end(sessionID: id) }.value }
            catch { self.error = "Audio stopped. Server hangup could not be confirmed." }
        }
        phase = .idle
    }
    private func fail(_ message: String) async {
        await end()
        error = message
        phase = .failed
    }
    private func handle(_ event: VoiceEvent) {
        switch event {
        case .ready:
            guard phase == .connecting else { return }
            watchdog?.cancel(); phase = .listening; peer?.mute(muted)
        case .level(let value):
            guard phase == .listening else { return }
            mouth = min(1, max(0, value))
        case .diagnostic(let text):
            guard phase == .listening else { return }
            audioDiagnostic = text
        case .packets(let sent, let received):
            guard phase == .listening else { return }
            packetsSent = sent; packetsReceived = received
        case .inputLevel(let value):
            guard phase == .listening else { return }
            microphoneLevel = muted ? 0 : min(1, max(0, value))
        case .transcript(let role, let delta):
            if role == "You" {
                rawUser = String((rawUser + delta).suffix(2000))
                userTranscript = Caption.spoken(rawUser)
            } else {
                rawAssistant = String((rawAssistant + delta).suffix(2000))
                assistantTranscript = Caption.spoken(rawAssistant)
            }
            if speaker != role { speaker = role; rawCaption = "" }
            rawCaption = String((rawCaption + delta).suffix(600))
            caption = Caption.spoken(rawCaption)
        case .closed: Task { await end() }
        case .lost: Task { await fail("Voice disconnected. Tap Talk to reconnect.") }
        case .failure(let message): Task { await fail(message) }
        }
    }
}
