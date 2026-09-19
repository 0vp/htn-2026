#if canImport(ARKit) && os(iOS)
import ARKit
import CoreImage
import Foundation

/// Owns a serial capture queue. No UIKit dependency; embed in the host iPhone app.
public final class CaptureController: NSObject, ARSessionDelegate {
    public let session = ARSession()
    private let queue = DispatchQueue(label: "htn.capture")
    private let context = CIContext()
    private let onPacket: (Data) -> Void
    private let onFrame: ((Data, FrameHeader) -> Void)?
    private let onError: (Error) -> Void
    private let maxRGBDimension = 960
    private var uploads = CaptureWindow()
    private var running = false
    private let onStatus: (String) -> Void
    private var sessionID = UUID().uuidString
    private var epoch = 0
    private var frameID = 0
    private var lastTimestamp = -Double.infinity

    public init(onPacket: @escaping (Data) -> Void, onError: @escaping (Error) -> Void,
                onStatus: @escaping (String) -> Void = { _ in },
                onFrame: ((Data, FrameHeader) -> Void)? = nil) {
        self.onFrame = onFrame
        self.onStatus = onStatus
        self.onPacket = onPacket
        self.onError = onError
        super.init()
        session.delegateQueue = queue
        session.delegate = self
    }

    public func start() { scheduleStart(restartOnly: false) }

    private func scheduleStart(restartOnly: Bool) {
        queue.async { [self] in
            guard !restartOnly || running else { return }
            guard ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) else {
                onError(CaptureError.lidarUnavailable)
                return
            }
            running = true
            onStatus("Move slowly to begin tracking")
            // Every new run has a new map epoch, even after interruption.
            epoch += 1
            frameID = 0
            lastTimestamp = -.infinity
            let configuration = ARWorldTrackingConfiguration()
            configuration.worldAlignment = .gravity
            configuration.frameSemantics = [.sceneDepth]
            session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        }
    }

    /// Resume the same local coordinate frame and packet sequence after a user pause.
    public func resume() {
        queue.async { [self] in
            guard !running else { return }
            // A user pause drains its uploader before Resume becomes available. Also clear
            // a reservation whose main-thread callback arrived just after capture stopped.
            uploads = CaptureWindow()
            running = true
            onStatus("Move slowly while tracking resumes")
            let configuration = ARWorldTrackingConfiguration()
            configuration.worldAlignment = .gravity
            configuration.frameSemantics = [.sceneDepth]
            session.run(configuration)
        }
    }

    public func stop(completion: @escaping () -> Void = {}) {
        queue.async { [self] in
            running = false
            session.pause()
            completion()
        }
    }

    /// Release one buffered capture after its transport acknowledgment.
    public func uploadCompleted() {
        queue.async { [self] in uploads.complete() }
    }

    public func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard running, uploads.hasCapacity, case .normal = frame.camera.trackingState,
              frame.timestamp - lastTimestamp >= 0.2,
              let scene = frame.sceneDepth,
              let confidence = scene.confidenceMap else { return }
        lastTimestamp = frame.timestamp
        do {
            let packet = try makePacket(frame, scene: scene, confidence: confidence)
            let encoded = try packet.encoded()
            let transmitted = encoded
            if onFrame != nil, !uploads.reserve(transmitted.count) {
                onStatus("Upload queue full · keep the app open while it catches up")
                return
            }
            onPacket(transmitted)
            onFrame?(transmitted, packet.header)
            frameID += 1
        } catch { onError(error) }
    }

    private func makePacket(_ frame: ARFrame, scene: ARDepthData,
                            confidence: CVPixelBuffer) throws -> FramePacket {
        let width = CVPixelBufferGetWidth(scene.depthMap)
        let height = CVPixelBufferGetHeight(scene.depthMap)
        let rgbWidth = CVPixelBufferGetWidth(frame.capturedImage)
        let rgbHeight = CVPixelBufferGetHeight(frame.capturedImage)
        let scale = min(1, Double(maxRGBDimension) / Double(max(rgbWidth, rgbHeight)))
        let outputWidth = Int((Double(rgbWidth) * scale).rounded())
        let outputHeight = Int((Double(rgbHeight) * scale).rounded())
        let image = CIImage(cvPixelBuffer: frame.capturedImage)
            .transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            .cropped(to: CGRect(x: 0, y: 0, width: outputWidth, height: outputHeight))
        guard let jpeg = context.jpegRepresentation(
            of: image,
            colorSpace: CGColorSpaceCreateDeviceRGB(),
            options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.7]
        ) else { throw CaptureError.jpegEncoding }
        let k = frame.camera.intrinsics
        let sx = Float(width) / Float(rgbWidth)
        let sy = Float(height) / Float(rgbHeight)
        let t = frame.camera.transform
        let transform = (0..<4).flatMap { column in (0..<4).map { row in t[column][row] } }
        let header = FrameHeader(
            session_id: sessionID, epoch: epoch, frame_id: frameID,
            timestamp_s: frame.timestamp, tracking: "normal", camera_convention: "arkit",
            depth_width: width, depth_height: height, rgb_width: outputWidth,
            rgb_height: outputHeight, rgb_bytes: jpeg.count,
            fx: k[0][0] * sx, fy: k[1][1] * sy, cx: k[2][0] * sx, cy: k[2][1] * sy,
            camera_to_world: transform
        )
        return FramePacket(header: header, depth: PixelBuffers.depth(scene.depthMap),
                           confidence: PixelBuffers.confidence(confidence), jpeg: jpeg)
    }

    public func sessionInterruptionEnded(_ session: ARSession) {
        scheduleStart(restartOnly: true)
    }

    public func sessionWasInterrupted(_ session: ARSession) {
        onStatus("Camera interrupted. Keep the app open.")
    }

    public func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        switch camera.trackingState {
        case .normal: onStatus("Tracking well")
        case .notAvailable: onStatus("Tracking unavailable")
        case .limited(let reason):
            switch reason {
            case .excessiveMotion: onStatus("Move more slowly")
            case .insufficientFeatures: onStatus("Point toward textured objects in good light")
            case .relocalizing: onStatus("Return to an area you already scanned")
            default: onStatus("Move slowly to begin tracking")
            }
        }
    }
    public func session(_ session: ARSession, didFailWithError error: Error) { onError(error) }

    public enum CaptureError: Error {
        case lidarUnavailable
        case jpegEncoding
    }
}
#endif
