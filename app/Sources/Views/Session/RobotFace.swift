import SwiftUI

struct RobotFace: View {
    var mouth: Double = 0
    var voicePhase: VoiceModel.Phase = .idle
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var blinking = false
    @State private var expression = 0
    private let faces = ["0_0", "^_^", ">_<"]
    private let names = ["Curious", "Happy", "Playful"]

    /// Left eye, mouth and right eye, kept apart so the mouth can sit lower than the eyes.
    private var parts: (String, String, String) {
        let eyes = voicePhase == .failed ? ">" : (voicePhase == .connecting ? "·" : (expression == 1 ? "^" : "0"))
        if voicePhase == .listening {
            let eye = blinking ? "−" : eyes
            return (eye, mouth > 0.4 ? "O" : mouth > 0.08 ? "o" : "_", eye)
        }
        if blinking { return ("−", "_", "−") }
        if voicePhase == .connecting { return ("·", "_", "·") }
        if voicePhase == .failed { return (">", "_", "<") }
        let face = Array(faces[expression])
        return (String(face[0]), String(face[1]), String(face[2]))
    }

    var body: some View {
        GeometryReader { geometry in
            let size = min(geometry.size.width * 0.42, geometry.size.height * 0.75, 180)
            let (left, lips, right) = parts
            // "o" and "O" sit mid-line while "_" rests on the baseline, so round mouths are
            // dropped to keep the mouth low on the face instead of jumping up when speaking.
            let drop = lips == "_" ? 0 : -size * 0.21
            Button { expression = (expression + 1) % faces.count } label: {
                Text("\(left)\(Text(lips).baselineOffset(drop))\(right)")
                    .font(.system(size: size, weight: .medium, design: .monospaced))
                    .minimumScaleFactor(0.5).lineLimit(1)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    // Swap mouth shapes instantly; a cross-fade made the lips trail the voice.
                    .contentTransition(.identity)
                    .transaction { $0.animation = nil }
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
