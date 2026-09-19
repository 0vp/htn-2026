import Combine
import Foundation

@MainActor
final class RoomsModel: ObservableObject {
    @Published var rooms: [Room] = []
    @Published var selected: RoomSession?
    @Published var busy = false
    @Published var error: String?
    let deviceID: String
    let api: RoomAPI

    init(api: RoomAPI = RoomAPI()) {
        self.api = api
        let key = "captureDeviceID"
        deviceID = UserDefaults.standard.string(forKey: key) ?? UUID().uuidString
        UserDefaults.standard.set(deviceID, forKey: key)
    }

    func refresh() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do { rooms = try await api.rooms(); error = nil }
        catch { self.error = error.localizedDescription }
    }

    func enter(code: String? = nil, name: String = "Room", role: DeviceRole = .angle) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let roomCode: String
            if let code { roomCode = code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() }
            else { roomCode = try await api.create(name: name).room_id }
            let room = try await api.join(code: roomCode, device: deviceID, role: role)
            selected = RoomSession(room: room, role: role)
            error = nil
        } catch { self.error = error.localizedDescription }
    }
}
