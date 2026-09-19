import SwiftUI

struct VoiceSheet: View {
    @ObservedObject var voice: VoiceModel
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Connect to Codex", isOn: Binding(get: { voice.codexEnabled }, set: { value in
                        Task { await voice.setCodex(value) }
                    })).disabled(voice.phase == .ending).accessibilityIdentifier("connectCodex")
                } footer: {
                    Text(voice.codexEnabled
                         ? "Codex can use your room’s tools while you keep talking. Changing this ends the current conversation."
                         : "Conversation only. No requests are sent to Codex and no room actions run.")
                }
                Section {
                    Label(voice.status, systemImage: voice.muted ? "mic.slash" : "waveform")
                    if let error = voice.error { Text(error).foregroundStyle(.secondary).accessibilityIdentifier("voiceError") }
                    if voice.active {
                        Button(voice.muted ? "Unmute microphone" : "Mute microphone") { voice.setMuted(!voice.muted) }
                        Button("End conversation", role: .destructive) { Task { await voice.end() } }
                    } else {
                        Button("Talk") { voice.start() }.disabled(voice.phase == .ending).accessibilityIdentifier("startVoice")
                    }
                } footer: { Text("Voice uses GPT-Live. The microphone is active only during a conversation.") }
                if !voice.caption.isEmpty {
                    Section(voice.speaker) { Text(voice.caption).textSelection(.enabled) }
                }
            }
            .navigationTitle("Voice").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }.presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
    }
}
