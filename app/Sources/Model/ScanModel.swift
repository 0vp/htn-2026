import ARKit
import AVFoundation
import Combine
import Foundation
import UIKit

@MainActor
final class ScanModel: ObservableObject {
    @Published private(set) var capturing = false
    @Published private(set) var captured = 0
    @Published private(set) var tracking = "Ready"
    @Published var error: String?
    let uploads: UploadQueue
    private let stream: FrameStream
    private let geographicContextAvailable: Bool
    private var observation: AnyCancellable?
    private var permissionPending = false
    private var finished = false
    private var restartAfterUpload = false
    static var supported: Bool { ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) }

    lazy var capture: CaptureController = CaptureController(
        onPacket: { _ in },
        onError: { [weak self] error in
            Task { @MainActor in
                self?.error = error.localizedDescription
                self?.pause()
            }
        },
        onStatus: { [weak self] status in Task { @MainActor in self?.tracking = status } },
        geographicContextAvailable: geographicContextAvailable,
        onFrame: { [weak self] data, header in
            Task { @MainActor in
                guard let self, !self.finished else { return }
                if self.uploads.enqueue(data, header: header) { self.captured += 1 }
                else {
                    self.capture.uploadCompleted()
                    self.error = "Upload buffer is full. Keep the app open and retry."
                    self.pause()
                    self.restartAfterUpload = true
                }
            }
        }
    )

    init(room: Room, device: String) {
        let stream = FrameStream(room: room.id, device: device)
        self.stream = stream
        geographicContextAvailable = room.geography?.schema_version == 1
        uploads = UploadQueue { data, header in try await stream.send(data, header: header) }
        uploads.acknowledged = { [weak self] in
            guard let self else { return }
            self.capture.uploadCompleted()
            if self.uploads.pending == 0, self.restartAfterUpload {
                self.restartAfterUpload = false
                Task { await self.start() }
            }
        }
        uploads.failed = { [weak self] in self?.pause() }
        observation = uploads.objectWillChange.sink { [weak self] in self?.objectWillChange.send() }
    }

    func start() async {
        guard !capturing, !permissionPending, !finished else { return }
        guard Self.supported else {
            error = "Scanning requires an iPhone with LiDAR."
            return
        }
        permissionPending = true
        let allowed = await AVCaptureDevice.requestAccess(for: .video)
        permissionPending = false
        guard !finished, UIApplication.shared.applicationState == .active else { return }
        guard allowed else {
            error = "Camera access is off. Enable it for HTN in Settings."
            return
        }
        guard uploads.pending == 0 else {
            restartAfterUpload = true
            return
        }
        error = nil
        capturing = true
        // A new epoch identifies each distinct camera coordinate frame.
        capture.start()
    }

    func pause() {
        restartAfterUpload = false
        capturing = false
        capture.stop()
    }

    func finish() {
        finished = true
        pause()
        stream.disconnect()
        uploads.discard()
    }
}
