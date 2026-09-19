import SwiftUI

struct RobotFace: View {
    var mouth: Double = 0
    var voicePhase: VoiceModel.Phase = .idle
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var blinking = false
    @State private var expression = 0
    private let faces = ["0_0", "^_^", ">_<"]
    private let names = ["Curious", "Happy", "Playful"]

    private var face: String {
        let eyes = voicePhase == .failed ? ">" : (voicePhase == .connecting ? "·" : (expression == 1 ? "^" : "0"))
        if voicePhase == .listening {
            let eye = blinking ? "−" : eyes
            return "\(eye)\(mouth > 0.4 ? "O" : mouth > 0.08 ? "o" : "_")\(eye)"
        }
        if blinking { return "−_−" }
        if voicePhase == .connecting { return "·_·" }
        if voicePhase == .failed { return ">_<" }
        return faces[expression]
    }

    var body: some View {
        GeometryReader { geometry in
            Button { expression = (expression + 1) % faces.count } label: {
                Text(face)
                    .font(.system(size: min(geometry.size.width * 0.42, geometry.size.height * 0.75, 180), weight: .medium, design: .monospaced))
                    .minimumScaleFactor(0.5).lineLimit(1)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .contentTransition(.opacity)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(names[expression]) robot face")
            .accessibilityHint("Double tap to change expression")
            .accessibilityIdentifier("robotFace")
        }
        .task(id: reduceMotion) {
            guard !reduceMotion else { blinking = false; return }
            while !Task.isCancelled {
                do {
                    try await Task.sleep(for: .seconds(6))
                    blinking = true
                    try await Task.sleep(for: .milliseconds(140))
                    blinking = false
                } catch { blinking = false; return }
            }
        }
    }
}
