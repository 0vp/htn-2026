import SwiftUI

struct ContentView: View {
    @StateObject private var model = RoomsModel()
    @State private var name = ""
    @State private var code = ""
    @State private var role: DeviceRole = .angle
    @FocusState private var focused: Field?

    private enum Field { case name, code }
    private let accent = Color(red: 0.33, green: 0.72, blue: 0.56)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    intro
                    startCard
                    joinCard
                    if let error = model.error { errorCard(error) }
                    sessions
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 32)
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("Momo")
            .navigationBarTitleDisplayMode(.large)
            .scrollDismissesKeyboard(.interactively)
            .refreshable { await model.refresh() }
            .task { await model.refresh() }
            .tint(accent)
            .fullScreenCover(item: $model.selected, onDismiss: { Task { await model.refresh() } }) { session in
                ScanView(room: session.room, device: model.deviceID, role: session.role)
            }
        }
    }

    private var intro: some View {
        HStack(spacing: 16) {
            Image("momo-neutral")
                .resizable().scaledToFill()
                .frame(width: 88, height: 88)
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text("Give your robot a face").font(.title2.bold())
                Text("One Head leads the session. Add Angle phones for a better map.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 8)
    }

    private var startCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("New session", systemImage: "plus.circle.fill")
                .font(.headline).foregroundStyle(accent)
            TextField("Session name", text: $name)
                .textFieldStyle(.roundedBorder).submitLabel(.go)
                .accessibilityIdentifier("roomName").focused($focused, equals: .name)
                .onSubmit { startSession() }
            Button(action: startSession) {
                HStack {
                    if model.busy { ProgressView().tint(.black) }
                    Text("Start as Head").fontWeight(.semibold)
                    Spacer()
                    Image(systemName: "arrow.right")
                }
                .frame(maxWidth: .infinity, minHeight: 28)
            }
            .buttonStyle(.borderedProminent)
            .buttonBorderShape(.roundedRectangle(radius: 14))
            .tint(accent).foregroundStyle(.black)
            .disabled(model.busy || name.count > 80)
            .accessibilityLabel("Create room")
        }
        .cardStyle()
    }

    private var joinCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("Join session", systemImage: "link").font(.headline)
            TextField("4-character code", text: $code)
                .font(.title3.monospaced().weight(.semibold))
                .textInputAutocapitalization(.characters).autocorrectionDisabled()
                .textFieldStyle(.roundedBorder).submitLabel(.join)
                .accessibilityIdentifier("roomCode").focused($focused, equals: .code)
                .onChange(of: code) { _, value in
                    code = String(value.uppercased().filter { $0.isHexDigit }.prefix(4))
                }
                .onSubmit { joinSession() }
            Picker("This phone is", selection: $role) {
                ForEach(DeviceRole.allCases) { role in
                    Label(role.rawValue, systemImage: role.icon).tag(role)
                }
            }
            .pickerStyle(.segmented)
            Text(role.detail).font(.caption).foregroundStyle(.secondary)
            Button("Join session", action: joinSession)
                .buttonStyle(.bordered)
                .buttonBorderShape(.roundedRectangle(radius: 14))
                .frame(maxWidth: .infinity)
                .disabled(model.busy || !RoomAPI.validCode(code))
        }
        .cardStyle()
    }

    private var sessions: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Open sessions").font(.headline)
                Spacer()
                if model.busy && model.rooms.isEmpty { ProgressView() }
            }
            if model.rooms.isEmpty && !model.busy {
                ContentUnavailableView("No open sessions", systemImage: "dot.radiowaves.left.and.right",
                    description: Text("Start one here, then connect the other phones with its code."))
                    .frame(maxWidth: .infinity).padding(.vertical, 12)
            } else {
                ForEach(model.rooms) { room in
                    Button { Task { await model.enter(code: room.id, role: .angle) } } label: {
                        HStack(spacing: 14) {
                            Image(systemName: "cube.transparent")
                                .font(.title3).frame(width: 40, height: 40)
                                .background(accent.opacity(0.16), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            VStack(alignment: .leading, spacing: 3) {
                                Text(room.name).font(.body.weight(.semibold)).foregroundStyle(.primary)
                                Text("\(room.id)  ·  \(room.frames_stored.formatted()) frames")
                                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right").font(.caption.bold()).foregroundStyle(.tertiary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain).disabled(model.busy)
                }
            }
        }
        .cardStyle()
    }

    private func errorCard(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.red)
            VStack(alignment: .leading, spacing: 6) {
                Text(message).font(.subheadline)
                Button("Try again") { Task { await model.refresh() } }.disabled(model.busy)
            }
            Spacer()
        }
        .cardStyle()
    }

    private func startSession() {
        focused = nil
        let value = name.trimmingCharacters(in: .whitespacesAndNewlines)
        Task { await model.enter(name: value.isEmpty ? "Robot session" : value, role: .head) }
    }

    private func joinSession() {
        focused = nil
        Task { await model.enter(code: code, role: role) }
    }
}

private extension View {
    func cardStyle() -> some View {
        padding(18)
            .background(Color(uiColor: .secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
