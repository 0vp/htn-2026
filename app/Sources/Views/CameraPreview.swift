import ARKit
import SwiftUI

struct CameraPreview: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView(frame: .zero)
        view.session = session
        view.automaticallyUpdatesLighting = false
        view.accessibilityLabel = "Camera preview"
        return view
    }

    func updateUIView(_ view: ARSCNView, context: Context) {}
}
