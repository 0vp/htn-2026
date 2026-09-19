import SwiftUI

struct RoomEntrySheet: View {
    let action: EntryAction
    @ObservedObject var model: RoomsModel
    let scanned: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var code = ""
    @State private var scanner = false
    @State private var scannedCode: String?

    var body: some View {
        NavigationStack {
            Form {
                if action == .create {
                    Section {
                        TextField("Room name", text: $name).accessibilityIdentifier("roomName")
                        Text("This phone will be the room’s face. Other phones can join from its Sync code.")
                            .foregroundStyle(.secondary)
                        Button("Create") {
                            Task {
                                let value = name.trimmingCharacters(in: .whitespacesAndNewlines)
                                await model.enter(name: value.isEmpty ? "My room" : value)
                                if model.selected != nil { dismiss() }
                            }
                        }.disabled(model.busy || name.count > 80)
                    }
                } else {
                    Section {
                        Button { scanner = true } label: {
                            Label("Scan room QR", systemImage: "qrcode.viewfinder")
                        }.disabled(model.busy)
                    } footer: { Text("Open Sync on the room’s main phone.") }
                    Section("Or enter a code") {
                        TextField("Room code", text: $code)
                            .textInputAutocapitalization(.characters).autocorrectionDisabled()
                            .font(.body.monospaced()).accessibilityIdentifier("roomCode")
                        Button("Join room") {
                            if let value = RoomLink.code(from: code) { scanned(value) }
                        }.disabled(model.busy || RoomLink.code(from: code) == nil)
                    }
                }
                if model.busy { ProgressView("Connecting…") }
                if let error = model.error { Text(error).foregroundStyle(.secondary) }
            }
            .navigationTitle(action == .create ? "Create room" : "Join room")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .sheet(isPresented: $scanner, onDismiss: {
                if let value = scannedCode {
                    scannedCode = nil
                    scanned(value)
                }
            }) {
                RoomQRScanner { value in
                    scanner = false
                    scannedCode = value
                }
            }

        }.interactiveDismissDisabled(model.busy)
    }
}
