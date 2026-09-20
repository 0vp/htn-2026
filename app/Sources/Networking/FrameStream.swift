import Foundation

struct UploadReceipt: Decodable {
    let stored: Bool?
    let frame_id: Int?
    let session_id: String?
    let epoch: Int?
    let room_id: String?
    let device_id: String?
    let error: String?
    let status: Int?

    func validate(_ header: FrameHeader, room: String, device: String) throws {
        if let error { throw StreamFailure(message: error, retryable: (status ?? 500) >= 500) }
        guard stored == true, frame_id == header.frame_id, epoch == header.epoch,
              session_id == header.session_id, room_id == room, device_id == device else {
            throw StreamFailure(message: "Upload acknowledgement did not match the frame.", retryable: false)
        }
    }
}

struct StreamFailure: LocalizedError {
    let message: String
    let retryable: Bool
    var errorDescription: String? { message }
}

@MainActor
final class FrameStream {
    private var socket: URLSessionWebSocketTask?
    private let session: URLSession
    private let url: URL
    private let room: String
    private let device: String

    init(base: URL = RoomAPI.server, room: String, device: String, session: URLSession = .shared) {
        var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        parts.scheme = parts.scheme == "https" ? "wss" : "ws"
        parts.path = "/v1/rooms/\(room)/devices/\(device)/stream"
        self.url = parts.url!
        self.room = room
        self.device = device
        self.session = session
    }

    func disconnect() {
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
    }

    func send(_ packet: Data, header: FrameHeader) async throws {
        try await MediaUploadBudget.shared.waitForTurn()
        if socket == nil {
            var request = URLRequest(url: url)
            request.networkServiceType = .background
            socket = session.webSocketTask(with: request)
            socket?.priority = URLSessionTask.lowPriority
            socket?.maximumMessageSize = 32_768
            socket?.resume()
        }
        let current = socket!
        do {
            let message = try await withThrowingTaskGroup(of: URLSessionWebSocketTask.Message.self) { group in
                group.addTask {
                    try await current.send(.data(packet))
                    return try await current.receive()
                }
                group.addTask {
                    try await Task.sleep(for: .seconds(15))
                    current.cancel(with: .goingAway, reason: nil)
                    throw URLError(.timedOut)
                }
                defer { group.cancelAll() }
                return try await group.next()!
            }
            let data: Data
            switch message {
            case .data(let value): data = value
            case .string(let value): data = Data(value.utf8)
            @unknown default: throw URLError(.badServerResponse)
            }
            try JSONDecoder().decode(UploadReceipt.self, from: data)
                .validate(header, room: room, device: device)
        } catch {
            disconnect()
            throw error
        }
    }
}
