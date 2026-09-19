import SwiftUI
import UIKit

struct RoomSessionView: View {
    @StateObject private var session: RoomSessionModel
    @StateObject private var scan: ScanModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var sync = false
    @State private var confirmLeave = false
    let leave: () -> Void

    init(room: Room, device: String, api: RoomAPI, leave: @escaping () -> Void) {
        _session = StateObject(wrappedValue: RoomSessionModel(room: room, device: device, api: api))
        _scan = StateObject(wrappedValue: ScanModel(room: room, device: device))
        self.leave = leave
    }

    var body: some View {
        VStack(spacing: 16) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(session.room.name).font(.headline).lineLimit(1)
                    Text(session.isLeader ? "Room leader" : "Contributor")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { confirmLeave = true } label: {
                    Image(systemName: "ellipsis").frame(width: 44, height: 44)
                }.accessibilityLabel("Room actions")
            }.padding(.horizontal, 24)
            if session.isLeader {
                RobotFace()
            } else {
                VStack(spacing: 20) {
                    Image(systemName: "viewfinder").font(.system(size: 64, weight: .light)).foregroundStyle(.tint)
                    Text("Another view.\nOne shared room.").font(.largeTitle.weight(.semibold)).multilineTextAlignment(.center)
                    Text("This phone contributes camera and LiDAR data. Keep the app open while scanning.")
                        .foregroundStyle(.secondary).multilineTextAlignment(.center).frame(maxWidth: 340)
                }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityIdentifier("contributorView")
            }
            VStack(spacing: 12) {
                Label(status, systemImage: statusIcon)
                    .font(.subheadline).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center).accessibilityIdentifier("sessionStatus")
                if ScanModel.supported, let message = scan.error {
                    Text(message).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    Button("Retry camera") { Task { await scan.start() } }.disabled(session.room.closed)
                }
                syncButton
            }.padding(.horizontal, 24).padding(.bottom, 16)
        }
        .padding(.top, 12)
        .background(Color(uiColor: .systemBackground))
        .sheet(isPresented: $sync) { SyncSheet(session: session, scan: scan) }
        .confirmationDialog("Room actions", isPresented: $confirmLeave, titleVisibility: .visible) {
            Button(scan.uploads.pending > 0 ? "Discard pending frames and leave" : "Leave room", role: .destructive) {
                scan.finish()
                leave()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(scan.uploads.pending > 0
                 ? "\(scan.uploads.pending) frames still need to upload. Leaving will discard them."
                 : "The room and its saved map will stay on the server.")
        }
        .interactiveDismissDisabled()
        .task { await session.observe() }
        .task { UIApplication.shared.isIdleTimerDisabled = true; await scan.start() }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { scan.pause() }
            else if !session.room.closed { Task { await scan.start() } }
        }
        .onChange(of: session.room.closed) { _, closed in if closed { scan.pause() } }
        .onDisappear { scan.finish(); UIApplication.shared.isIdleTimerDisabled = false }
    }

    private var status: String {
        if session.room.closed { return "Room closed" }
        if !ScanModel.supported { return "Camera streaming needs an iPhone with LiDAR" }
        if let error = session.connectionError { return error }
        if scan.uploads.message != nil { return "Reconnecting · frames waiting to upload" }
        if scan.error != nil { return "Camera needs attention" }
        if !scan.capturing { return "Camera paused" }
        if scan.uploads.stored == 0 { return "Connecting camera…" }
        return "Streaming to room"
    }

    private var statusIcon: String {
        scan.capturing && scan.uploads.message == nil ? "video.fill" : "info.circle"
    }

    @ViewBuilder private var syncButton: some View {
        if #available(iOS 26.0, *) {
            Button { sync = true } label: { Label("Sync", systemImage: "qrcode").padding(.horizontal, 24) }
                .buttonStyle(.glass).controlSize(.large).buttonBorderShape(.capsule)
        } else {
            Button { sync = true } label: {
                Label("Sync", systemImage: "qrcode").padding(.horizontal, 32).padding(.vertical, 16)
                    .background(.regularMaterial, in: Capsule())
            }.buttonStyle(.plain)
        }
    }
}
