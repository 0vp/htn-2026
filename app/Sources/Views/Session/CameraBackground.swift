import ARKit
import SwiftUI

/// Displays the existing ARKit camera texture without another capture or encoding path.
struct CameraBackground: UIViewRepresentable {
    let session: ARSession
    let active: Bool

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView(frame: .zero)
        view.session = session
        view.automaticallyUpdatesLighting = false
        view.preferredFramesPerSecond = 15
        view.isUserInteractionEnabled = false
        view.accessibilityElementsHidden = true
        view.backgroundColor = .black
        return view
    }

    func updateUIView(_ view: ARSCNView, context: Context) {
        view.isPlaying = active
        // Never imply that a paused, frozen camera texture is a live preview.
        view.isHidden = !active
    }

    static func dismantleUIView(_ view: ARSCNView, coordinator: ()) {
        view.isPlaying = false
        // ScanModel owns session start/pause; this renderer must not reset its map.
    }
}
