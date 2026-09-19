import SwiftUI

struct ContentView: View {
    @StateObject private var model = RoomsModel()
    @State private var name = ""
    @State private var code = ""
    @FocusState private var focused: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Create a room") {
                    TextField("Room name", text: $name).accessibilityIdentifier("roomName").focused($focused, equals: "name")
                    Button("Create room") {
                        focused = nil
                        let value = name.trimmingCharacters(in: .whitespacesAndNewlines)
                        Task { await model.enter(name: value.isEmpty ? "Room" : value) }
                    }
                    .disabled(model.busy || name.count > 80)
                }
                Section("Join a room") {
                    TextField("Room code", text: $code)
                        .textInputAutocapitalization(.characters).autocorrectionDisabled()
                        .accessibilityIdentifier("roomCode").focused($focused, equals: "code")
                    Button("Join room") { focused = nil; Task { await model.enter(code: code) } }
                        .disabled(model.busy || !RoomAPI.validCode(code.uppercased()))
                }
                if let error = model.error {
                    Section {
                        Text(error).foregroundStyle(.secondary)
                        Button("Try again") { Task { await model.refresh() } }.buttonStyle(.plain).disabled(model.busy)
                    }
                }
                Section("Open rooms") {
                    if model.rooms.isEmpty {
                        Text(model.busy ? "Loading rooms…" : "No open rooms")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(model.rooms) { room in
                        Button { Task { await model.enter(code: room.id) } } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(room.name).foregroundStyle(.primary)
                                Text("\(room.id) · \(room.frames_stored) frames saved")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }.buttonStyle(.plain).disabled(model.busy)
                    }
                }
            }
            .navigationTitle("Rooms")
            .scrollDismissesKeyboard(.interactively)
            .refreshable { await model.refresh() }
            .task { await model.refresh() }
            .fullScreenCover(item: $model.selected, onDismiss: { Task { await model.refresh() } }) { room in
                ScanView(room: room, device: model.deviceID)
            }
        }
    }
}
