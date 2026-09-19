import SwiftUI
import UIKit

struct ScanView: View {
    let room: Room
    @StateObject private var model: ScanModel
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var confirmDiscard = false

    init(room: Room, device: String) {
        self.room = room
        _model = StateObject(wrappedValue: ScanModel(room: room, device: device))
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("Room code", value: room.id).textSelection(.enabled)
                        .accessibilityIdentifier("activeRoomCode").accessibilityValue(room.id)
                    ShareLink("Share room code", item: room.id)
                }
                if ScanModel.supported {
                    Section {
                        CameraPreview(session: model.capture.session)
                            .frame(height: 220).listRowInsets(EdgeInsets())
                    }
                } else {
                    Section {
                        ContentUnavailableView("LiDAR required", systemImage: "camera",
                            description: Text("Use a LiDAR-equipped iPhone to capture this room."))
                    }
                }
                Section("This capture") {
                    LabeledContent("Captured", value: "\(model.captured)")
                    LabeledContent("Saved on server", value: "\(model.uploads.stored)")
                    LabeledContent("Waiting to upload", value: "\(model.uploads.pending)")
                    Text(model.tracking).foregroundStyle(.secondary)
                }
                .monospacedDigit()
                if let message = model.error ?? model.uploads.message {
                    Section {
                        Text(message).foregroundStyle(.secondary)
                        if model.uploads.pending > 0 {
                            Button("Retry uploads") { model.uploads.retry() }
                        }
                    }
                }
                Section {
                    Button(model.capturing ? "Pause capture" : "Start capture") {
                        if model.capturing { model.pause() }
                        else { Task { await model.start() } }
                    }
                    .disabled(!ScanModel.supported || (!model.capturing && model.uploads.pending > 0))
                } footer: {
                    Text("Keep the app open until every captured frame is saved on the server.")
                }
            }
            .navigationTitle(room.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        model.pause()
                        if model.uploads.pending > 0 { confirmDiscard = true }
                        else { model.finish(); dismiss() }
                    }
                }
            }
            .confirmationDialog("Some frames have not uploaded", isPresented: $confirmDiscard,
                                titleVisibility: .visible) {
                Button("Discard pending frames", role: .destructive) { model.finish(); dismiss() }
                Button("Keep uploading", role: .cancel) {}
            }
        }
        .interactiveDismissDisabled(model.capturing || model.uploads.pending > 0)
        .onChange(of: scenePhase) { _, phase in if phase != .active { model.pause() } }
        .onChange(of: model.capturing) { _, _ in updateIdleTimer() }
        .onChange(of: model.uploads.pending) { _, _ in updateIdleTimer() }
        .onDisappear { model.finish(); UIApplication.shared.isIdleTimerDisabled = false }
    }

    private func updateIdleTimer() {
        UIApplication.shared.isIdleTimerDisabled = model.capturing || model.uploads.pending > 0
    }
}
