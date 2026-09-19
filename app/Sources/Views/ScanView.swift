import SwiftUI
import UIKit

struct ScanView: View {
    let room: Room
    let role: DeviceRole
    @StateObject private var model: ScanModel
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var confirmDiscard = false

    private let accent = Color(red: 0.33, green: 0.72, blue: 0.56)

    init(room: Room, device: String, role: DeviceRole = .angle) {
        self.room = room
        self.role = role
        _model = StateObject(wrappedValue: ScanModel(room: room, device: device))
    }

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()
                if role == .head {
                    RobotFaceView(active: model.capturing).ignoresSafeArea()
                } else if ScanModel.supported {
                    CameraPreview(session: model.capture.session).ignoresSafeArea()
                    ScanReticle()
                } else {
                    VStack(spacing: 16) {
                        Image(systemName: "camera.metering.unknown")
                            .font(.system(size: 48, weight: .light)).foregroundStyle(accent)
                        Text("LiDAR required").font(.title2.bold())
                        Text("Use a LiDAR-equipped iPhone as this Angle phone.")
                            .multilineTextAlignment(.center).foregroundStyle(.secondary)
                    }
                    .padding(32)
                }
            }
            .safeAreaInset(edge: .bottom) { controls }
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Text(room.id).font(.caption.monospaced().weight(.bold))
                        .accessibilityLabel("Session code").accessibilityIdentifier("activeRoomCode")
                        .accessibilityValue(room.id)
                }
                ToolbarItem(placement: .principal) {
                    Text(role.rawValue).font(.subheadline.weight(.semibold))
                }
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
        .tint(accent)
        .interactiveDismissDisabled(model.capturing || model.uploads.pending > 0)
        .task { if ScanModel.supported { await model.start() } }
        .onChange(of: scenePhase) { _, phase in if phase != .active { model.pause() } }
        .onChange(of: model.capturing) { _, _ in updateIdleTimer() }
        .onChange(of: model.uploads.pending) { _, _ in updateIdleTimer() }
        .onDisappear { model.finish(); UIApplication.shared.isIdleTimerDisabled = false }
    }

    private var controls: some View {
        VStack(spacing: 14) {
            HStack(spacing: 20) {
                metric("Captured", model.captured)
                Divider().frame(height: 34)
                metric("Saved", model.uploads.stored)
                Divider().frame(height: 34)
                metric("Uploading", model.uploads.pending)
            }
            if let message = model.error ?? model.uploads.message {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(.yellow).lineLimit(2)
            } else {
                Label(ScanModel.supported ? model.tracking : "LiDAR required",
                      systemImage: model.capturing ? "dot.radiowaves.left.and.right" : "pause.circle")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            HStack(spacing: 12) {
                ShareLink(item: room.id) {
                    Image(systemName: "square.and.arrow.up").frame(width: 28, height: 28)
                }
                .buttonStyle(.bordered).accessibilityLabel("Share session code")
                if model.uploads.pending > 0 && !model.capturing {
                    Button("Retry uploads") { model.uploads.retry() }.buttonStyle(.bordered)
                }
                Button {
                    if model.capturing { model.pause() }
                    else { Task { await model.start() } }
                } label: {
                    Label(model.capturing ? "Pause capture" : "Start capture",
                          systemImage: model.capturing ? "pause.fill" : "record.circle")
                        .frame(maxWidth: .infinity, minHeight: 28).fontWeight(.semibold)
                }
                .buttonStyle(.borderedProminent).buttonBorderShape(.roundedRectangle(radius: 14))
                .disabled(!ScanModel.supported || (!model.capturing && model.uploads.pending > 0))
            }
            Text("Keep this app open until Uploading reaches zero.")
                .font(.caption2).foregroundStyle(.tertiary)
        }
        .padding(16)
        .background(.regularMaterial)
        .colorScheme(.dark)
    }

    private func metric(_ label: String, _ value: Int) -> some View {
        VStack(spacing: 2) {
            Text(value.formatted()).font(.title3.bold().monospacedDigit())
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private func updateIdleTimer() {
        UIApplication.shared.isIdleTimerDisabled = model.capturing || model.uploads.pending > 0
    }
}
