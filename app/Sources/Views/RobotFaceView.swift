import SwiftUI

struct RobotFaceView: View {
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 24.0, paused: reduceMotion)) { timeline in
            let time = timeline.date.timeIntervalSinceReferenceDate
            let blink = active && time.truncatingRemainder(dividingBy: 4.6) < 0.16
            Image(blink ? "momo-speaking" : "momo-neutral")
                .resizable()
                .scaledToFill()
                .scaleEffect(reduceMotion ? 1 : 1 + sin(time * 0.85) * 0.004)
                .offset(y: reduceMotion ? 0 : sin(time * 0.85) * 2)
                .animation(.easeOut(duration: 0.08), value: blink)
                .accessibilityLabel(active ? "Momo is awake and scanning" : "Momo is waiting")
        }
        .background(Color(red: 0.06, green: 0.08, blue: 0.07))
        .clipped()
    }
}

struct ScanReticle: View {
    var body: some View {
        ZStack {
            Circle().stroke(.white.opacity(0.9), lineWidth: 1).frame(width: 88, height: 88)
            Circle().fill(.white).frame(width: 5, height: 5)
            ForEach(0..<4) { index in
                Capsule().fill(.white.opacity(0.9)).frame(width: 22, height: 2)
                    .offset(x: 54).rotationEffect(.degrees(Double(index) * 90))
            }
        }
        .shadow(color: .black.opacity(0.4), radius: 8)
        .accessibilityHidden(true)
    }
}
