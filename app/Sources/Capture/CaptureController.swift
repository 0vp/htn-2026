#if canImport(ARKit) && os(iOS)
import ARKit
import CoreImage
import CoreLocation
import UIKit
import Foundation

/// Owns a serial capture queue. No UIKit dependency; embed in the host iPhone app.
public final class CaptureController: NSObject, ARSessionDelegate {
    public let session = ARSession()
    private let queue = DispatchQueue(label: "htn.capture", qos: .utility)
    private let context = CIContext()
    private let geography = GeographicCapture()
    private let geographicContextAvailable: Bool
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
                geographicContextAvailable: Bool = false,
                onFrame: ((Data, FrameHeader) -> Void)? = nil) {
        self.geographicContextAvailable = geographicContextAvailable
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
            geography.reset()
            if geographicContextAvailable {
                DispatchQueue.main.async { [self] in geography.start() }
            }
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
            if geographicContextAvailable {
                DispatchQueue.main.async { [self] in geography.start() }
            }
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
            DispatchQueue.main.async { [self] in geography.stop() }
            completion()
        }
    }

    /// Release camera memory after upload, replacement, or explicit discard.
    public func uploadCompleted(bytes: Int) {
        queue.async { [self] in uploads.complete(bytes) }
    }

    public func session(_ session: ARSession, didUpdate frame: ARFrame) {
        if running, geographicContextAvailable, case .normal = frame.camera.trackingState { geography.observe(frame) }
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
            if let anchor = packet.header.geographic_anchor {
                geography.emitted(anchor, at: frame.timestamp)
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
            camera_to_world: transform,
            geographic_anchor: geographicContextAvailable ? geography.anchor(at: frame.timestamp) : nil
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

#if canImport(ARKit) && os(iOS)
/// Main-thread Core Location callbacks, capture-queue pose sampling; no UI dependencies.
private final class GeographicCapture: NSObject, CLLocationManagerDelegate {
    private struct Pose {
        let uptime: Double
        let unix: Double
        let transform: [Float]
        let headingDirection: [Float]
    }
    private let manager = CLLocationManager()
    private let lock = NSLock()
    private var poses: [Pose] = []
    private var location: CLLocation?
    private var heading: CLHeading?
    private var previous: GeographicAnchor?
    private var emittedAt = -Double.infinity
    private var active = false

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        manager.headingFilter = 5
        // Match this fixed physical axis to the AR view below, independent of UI rotation.
        manager.headingOrientation = .landscapeRight
    }

    func start() {
        active = true
        switch manager.authorizationStatus {
        case .notDetermined: manager.requestWhenInUseAuthorization()
        case .authorizedAlways, .authorizedWhenInUse:
            manager.startUpdatingLocation()
            if CLLocationManager.headingAvailable() { manager.startUpdatingHeading() }
        default:
            stop(); reset() // GPS denial must never block LiDAR capture.
        }
    }

    func stop() {
        active = false
        manager.stopUpdatingLocation()
        manager.stopUpdatingHeading()
    }

    func reset() {
        lock.lock(); defer { lock.unlock() }
        poses.removeAll(); previous = nil; emittedAt = -.infinity
        location = nil; heading = nil
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        if active { start() }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let value = locations.last, CLLocationCoordinate2DIsValid(value.coordinate),
              value.horizontalAccuracy.isFinite, value.horizontalAccuracy >= 0 else { return }
        lock.lock(); defer { lock.unlock() }
        if location == nil || value.timestamp >= location!.timestamp { location = value }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateHeading value: CLHeading) {
        guard value.headingAccuracy.isFinite, (0...180).contains(value.headingAccuracy) else { return }
        lock.lock(); defer { lock.unlock() }
        heading = value
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // Optional metadata: location failures do not interrupt frame streaming.
    }

    func observe(_ frame: ARFrame) {
        let transform = frame.camera.transform
        let axis = frame.camera.viewMatrix(for: .landscapeRight).inverse.columns.1
        let pose = Pose(uptime: frame.timestamp,
                        unix: Date().timeIntervalSince1970 + frame.timestamp - ProcessInfo.processInfo.systemUptime,
                        transform: (0..<4).flatMap { c in (0..<4).map { r in transform[c][r] } },
                        headingDirection: [axis.x, axis.y, axis.z])
        lock.lock(); defer { lock.unlock() }
        poses.append(pose)
        poses.removeAll { frame.timestamp - $0.uptime > 6 }
    }

    func anchor(at uptime: Double) -> GeographicAnchor? {
        lock.lock(); defer { lock.unlock() }
        guard uptime - emittedAt >= 10, let fix = location,
              abs(Date().timeIntervalSince(fix.timestamp)) <= 5,
              let pose = nearest(fix.timestamp) else { return nil }
        var bearing: GeographicHeading?
        if let h = heading, abs(h.timestamp.timeIntervalSince(fix.timestamp)) <= 3,
           let hp = nearest(h.timestamp) {
            let degrees = h.trueHeading >= 0 ? h.trueHeading : h.magneticHeading
            if degrees.isFinite, (0..<360).contains(degrees) {
                bearing = GeographicHeading(
                    degrees: degrees, accuracy_degrees: h.headingAccuracy,
                    reference: h.trueHeading >= 0 ? "true_north" : "magnetic_north",
                    timestamp_unix_s: h.timestamp.timeIntervalSince1970,
                    pose_timestamp_s: hp.uptime, pose_time_offset_s: hp.unix - h.timestamp.timeIntervalSince1970,
                    camera_to_world: hp.transform, reference_direction_world: hp.headingDirection)
            }
        }
        let candidate = GeographicAnchor(
            latitude: fix.coordinate.latitude, longitude: fix.coordinate.longitude,
            horizontal_accuracy_m: fix.horizontalAccuracy,
            timestamp_unix_s: fix.timestamp.timeIntervalSince1970,
            pose_timestamp_s: pose.uptime, pose_time_offset_s: pose.unix - fix.timestamp.timeIntervalSince1970,
            camera_to_world: pose.transform, heading: bearing)
        if let previous, !candidate.improves(previous) { return nil }
        return candidate
    }

    func emitted(_ anchor: GeographicAnchor, at uptime: Double) {
        lock.lock(); defer { lock.unlock() }
        previous = anchor; emittedAt = uptime
    }

    private func nearest(_ timestamp: Date) -> Pose? {
        let unix = timestamp.timeIntervalSince1970
        guard let pose = poses.min(by: { abs($0.unix - unix) < abs($1.unix - unix) }),
              abs(pose.unix - unix) <= 0.35 else { return nil }
        return pose
    }
}
#endif
