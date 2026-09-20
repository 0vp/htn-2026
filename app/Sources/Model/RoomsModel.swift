import Combine
import Foundation

@MainActor
final class RoomsModel: ObservableObject {
    @Published var rooms: [Room] = []
    @Published var selected: Room?
    @Published var busy = false
    @Published var error: String?
    let deviceID: String
    let api: RoomAPI
    private var restored = false
    private let rememberedKey = "activeRoomCode"
    /// The deployment has exactly one always-open room (backend HTN_ROOM_ID).
    static let worldCode = "A0000001"

    init(api: RoomAPI = RoomAPI()) {
        self.api = api
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--reset-room-for-testing") {
            UserDefaults.standard.removeObject(forKey: rememberedKey)
        }
        #endif
        let key = "captureDeviceID"
        deviceID = UserDefaults.standard.string(forKey: key) ?? UUID().uuidString
        UserDefaults.standard.set(deviceID, forKey: key)
    }

    func restore() async {
        guard !restored else { return }
        restored = true
        await enterWorld()
    }

    func enterWorld() async { await enter(code: Self.worldCode) }

    func leave() { selected = nil }

    func refresh() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do { rooms = try await api.rooms(); error = nil }
        catch { self.error = error.localizedDescription }
    }

    func enter(code: String? = nil, name: String = "Room") async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let room: Room
            if let code {
                let normalized = code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
                room = try await api.join(code: normalized, device: deviceID)
            } else { room = try await api.create(name: name, device: deviceID) }
            guard !room.closed else { throw APIError(message: "This room is closed. Create or join another room.") }
            selected = room
            UserDefaults.standard.set(room.id, forKey: rememberedKey)
            error = nil
        } catch { self.error = error.localizedDescription }
    }
}
