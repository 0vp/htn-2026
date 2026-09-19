import Foundation

struct Room: Decodable, Identifiable, Equatable {
    let room_id: String
    let name: String
    let closed: Bool
    let frames_stored: Int
    var id: String { room_id }
}

enum DeviceRole: String, CaseIterable, Identifiable {
    case head = "Head"
    case angle = "Angle"

    var id: Self { self }
    var icon: String { self == .head ? "face.smiling" : "camera.viewfinder" }
    var detail: String {
        self == .head ? "Robot face + LiDAR capture" : "Extra angle for map alignment"
    }
}

struct RoomSession: Identifiable {
    let room: Room
    let role: DeviceRole
    var id: String { room.id }
}

struct APIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

private struct ServerFailure: Decodable { let detail: String }

struct RoomAPI {
    static let server: URL = {
        #if DEBUG
        if let address = ProcessInfo.processInfo.environment["HTN_TEST_SERVER"],
           let url = URL(string: address) { return url }
        #endif
        return URL(string: "https://qasim-test.35-253-10-71.sslip.io")!
    }()
    let base: URL
    let session: URLSession

    init(base: URL = server, session: URLSession = .shared) {
        self.base = base
        self.session = session
    }

    func rooms() async throws -> [Room] {
        struct List: Decodable { let rooms: [Room] }
        let result: List = try await request("v1/rooms")
        return result.rooms.filter { !$0.closed && Self.validCode($0.id) }
    }

    func create(name: String) async throws -> Room {
        try await request("v1/rooms", body: ["name": name])
    }

    func join(code: String, device: String, role: DeviceRole = .angle) async throws -> Room {
        guard Self.validCode(code) else { throw APIError(message: "Enter the four-character session code.") }
        return try await request("v1/rooms/\(code)/join", body: ["device_id": device, "name": role.rawValue])
    }

    static func validCode(_ code: String) -> Bool {
        code.count == 4 && code.allSatisfy { "0123456789ABCDEF".contains($0) }
    }

    private func request<T: Decodable>(_ path: String, body: [String: String]? = nil) async throws -> T {
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.timeoutInterval = 15
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let message = (try? JSONDecoder().decode(ServerFailure.self, from: data).detail)
                ?? "The server could not complete the request. Try again."
            throw APIError(message: message)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
