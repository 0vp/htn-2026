import SwiftUI

struct ContentView: View {
    @StateObject private var model = RoomsModel()
    @State private var action: EntryAction?
    @State private var pendingCode: String?
    @State private var displayedRoom: Room?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 32) {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("0_0").font(.system(size: 64, weight: .medium, design: .monospaced))
                            .foregroundStyle(.tint).accessibilityHidden(true)
                        Text("A room to see together.").font(.title2.weight(.semibold))
                        Text("Create a room on your robot’s phone, or join to add another view.")
                            .foregroundStyle(.secondary)
                    }
                    VStack(spacing: 12) {
                        Button { action = .create } label: {
                            Label("Create room", systemImage: "plus").frame(maxWidth: .infinity, minHeight: 36)
                        }.buttonStyle(.borderedProminent)
                        Button { action = .join } label: {
                            Label("Scan QR to join", systemImage: "qrcode.viewfinder")
                                .frame(maxWidth: .infinity, minHeight: 36)
                        }.buttonStyle(.bordered)
                    }.disabled(model.busy)
                    if model.busy { ProgressView("Connecting…") }
                    if let error = model.error {
                        Text(error).foregroundStyle(.secondary).accessibilityIdentifier("roomError")
                    }
                    if !model.rooms.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Open rooms").font(.headline)
                            ForEach(model.rooms) { room in
                                Button { Task { await model.enter(code: room.id) } } label: {
                                    HStack {
                                        Image(systemName: "square.stack.3d.up").foregroundStyle(.tint)
                                        VStack(alignment: .leading) {
                                            Text(room.name).foregroundStyle(.primary)
                                            Text(room.id).font(.caption.monospaced()).foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        Image(systemName: "chevron.right").foregroundStyle(.tertiary)
                                    }.padding(.vertical, 12).contentShape(Rectangle())
                                }.buttonStyle(.plain).disabled(model.busy)
                                Divider()
                            }
                        }
                    }
                }.padding(24).frame(maxWidth: 560)
            }
            .navigationTitle("Rooms")
            .refreshable { await model.refresh() }
            .task { await model.restore() }
            .sheet(item: $action, onDismiss: enterPendingRoom) { action in
                RoomEntrySheet(action: action, model: model) { code in
                    pendingCode = code
                    self.action = nil
                }
            }
            .onChange(of: model.selected) { _, room in if action == nil { displayedRoom = room } }
            .fullScreenCover(item: $displayedRoom) { room in
                RoomSessionView(room: room, device: model.deviceID, api: model.api) { model.leave() }
            }
            .onOpenURL { url in
                guard let code = RoomLink.code(from: url.absoluteString) else {
                    model.error = "That link does not contain a valid room code."
                    return
                }
                guard model.selected == nil else { return }
                pendingCode = code
                if action != nil { action = nil } else { enterPendingRoom() }
            }
        }.tint(.blue)
    }

    private func enterPendingRoom() {
        guard let code = pendingCode else { displayedRoom = model.selected; return }
        pendingCode = nil
        Task { await model.enter(code: code) }
    }
}

enum EntryAction: String, Identifiable {
    case create, join
    var id: String { rawValue }
}
