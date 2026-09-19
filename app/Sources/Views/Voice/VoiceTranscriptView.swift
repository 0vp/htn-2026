import SwiftUI

/// Independent captions preserve overlapping speech from the full-duplex call.
struct VoiceTranscriptView: View {
    @ObservedObject var voice: VoiceModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label(voice.status, systemImage: voice.muted ? "mic.slash" : "waveform")
                Spacer()
                if voice.phase == .connecting { ProgressView() }
                if voice.phase == .listening {
                    Text(voice.microphoneLevel > 0.03 ? "Audio detected" : "No mic activity")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.font(.subheadline).accessibilityIdentifier("voiceStatus")
            if let error = voice.error {
                Text(error).font(.footnote).foregroundStyle(.red)
                    .accessibilityIdentifier("roomVoiceError")
            }
            VStack(alignment: .leading, spacing: 10) {
                caption("You", text: voice.userTranscript,
                        placeholder: voice.active ? "Waiting for recognized speech…" : "Tap Talk to start.", id: "userTranscript")
                caption("Assistant", text: voice.assistantTranscript,
                        placeholder: "No reply yet.", id: "assistantTranscript")
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(12)
        .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func caption(_ name: String, text: String, placeholder: String, id: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(name).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            ScrollViewReader { reader in
                ScrollView {
                    Text(text.isEmpty ? placeholder : text)
                        .font(.subheadline).foregroundStyle(text.isEmpty ? .secondary : .primary)
                        .textSelection(.enabled).accessibilityIdentifier(id)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Color.clear.frame(height: 1).id("latest")
                }
                .frame(maxHeight: 52)
                .onChange(of: text) { _, _ in reader.scrollTo("latest", anchor: .bottom) }
            }
        }
    }
}
