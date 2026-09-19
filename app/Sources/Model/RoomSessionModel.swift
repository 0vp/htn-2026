import Combine
import Foundation

@MainActor
final class RoomSessionModel: ObservableObject {
    @Published private(set) var room: Room
    @Published private(set) var processing: RoomProcessing?
    @Published private(set) var connectionError: String?
    let device: String
    private let api: RoomAPI
    var isLeader: Bool { room.leader_device_id == device }

    init(room: Room, device: String, api: RoomAPI) {
        self.room = room
        self.device = device
        self.api = api
    }

    func observe() async {
        while !Task.isCancelled {
            do {
                async let current = api.room(code: room.id)
                async let status = api.processing(code: room.id)
                let values = try await (current, status)
                guard !Task.isCancelled else { return }
                room = values.0
                processing = values.1
                connectionError = room.closed ? "This room has been closed." : nil
            } catch {
                guard !Task.isCancelled else { return }
                connectionError = "Reconnecting to the room…"
            }
            do { try await Task.sleep(for: .seconds(3)) } catch { return }
        }
    }
}
