import XCTest
@testable import HTNApp

final class BackendIntegrationTests: XCTestCase {
    @MainActor
    func testSwiftPacketOverWebSocketAndHTTPRetry() async throws {
        let base = URL(string: "http://127.0.0.1:8897")!
        var probe = URLRequest(url: base.appendingPathComponent("health"))
        probe.timeoutInterval = 2
        do { _ = try await URLSession.shared.data(for: probe) }
        catch { throw XCTSkip("Start the local backend on port 8897 for integration tests.") }
        let api = RoomAPI(base: base)
        let room = try await api.create(name: "Swift transport check")
        let device = UUID().uuidString
        let joined = try await api.join(code: room.id, device: device)
        XCTAssertEqual(joined.id, room.id)
        let header = FrameHeader(session_id: "swift-test", epoch: 1, frame_id: 0,
            timestamp_s: 0, tracking: "normal", camera_convention: "arkit",
            depth_width: 2, depth_height: 1, rgb_width: 0, rgb_height: 0, rgb_bytes: 0,
            fx: 2, fy: 2, cx: 1, cy: 0,
            camera_to_world: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
        let data = try FramePacket(header: header, depth: [1.25, 2.5],
                                  confidence: Data([2, 1]), jpeg: Data()).encoded()
        let stream = FrameStream(base: base, room: room.id, device: device)
        defer { stream.disconnect() }
        try await stream.send(data, header: header)
        stream.disconnect()
        try await stream.send(data, header: header)
        var request = URLRequest(url: base.appendingPathComponent("v1/rooms/\(room.id)/devices/\(device)/frames"))
        request.httpMethod = "POST"
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.httpBody = data
        let (result, response) = try await URLSession.shared.data(for: request)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
        let receipt = try XCTUnwrap(JSONSerialization.jsonObject(with: result) as? [String: Any])
        XCTAssertEqual(receipt["duplicate"] as? Bool, true)
        let rooms = try await api.rooms()
        XCTAssertEqual(rooms.first { $0.id == room.id }?.frames_stored, 1)
        let sequence = try XCTUnwrap(receipt["sequence"] as? Int)
        let (stored, _) = try await URLSession.shared.data(from: base.appendingPathComponent("v1/rooms/\(room.id)/frames/\(sequence)"))
        XCTAssertEqual(stored, data)
    }
}
