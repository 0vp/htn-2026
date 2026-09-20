import XCTest
@testable import HTNApp

final class TransportTests: XCTestCase {
    func header() -> FrameHeader {
        FrameHeader(session_id: "test", epoch: 1, frame_id: 2, timestamp_s: 3,
                    tracking: "normal", camera_convention: "arkit", depth_width: 1,
                    depth_height: 1, rgb_width: 0, rgb_height: 0, rgb_bytes: 0,
                    fx: 1, fy: 1, cx: 0, cy: 0,
                    camera_to_world: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
    }

    func testPacketLayoutAndReceiptIdentity() throws {
        let data = try FramePacket(header: header(), depth: [1.25], confidence: Data([2]), jpeg: Data()).encoded()
        XCTAssertEqual(String(data: data.prefix(4), encoding: .utf8), "R3D1")
        XCTAssertEqual(Array(data.suffix(5)), [0, 0, 160, 63, 2])
        let good = UploadReceipt(stored: true, frame_id: 2, session_id: "test", epoch: 1,
                                 room_id: "ABCDEF12", device_id: "phone", error: nil, status: nil)
        XCTAssertNoThrow(try good.validate(header(), room: "ABCDEF12", device: "phone"))
        XCTAssertThrowsError(try good.validate(header(), room: "ABCDEF12", device: "other"))
        XCTAssertThrowsError(try FramePacket(header: header(), depth: [1], confidence: Data([3]), jpeg: Data()).encoded())
    }

    @MainActor
    func testAcknowledgedOnlyAfterSendAndPermanentFailureKeepsFrame() async throws {
        var calls = 0
        let queue = UploadQueue { _, _ in
            calls += 1
            if calls == 1 { throw StreamFailure(message: "closed", retryable: false) }
        }
        XCTAssertTrue(queue.enqueue(Data([1, 2]), header: header()))
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(queue.pending, 1)
        XCTAssertEqual(queue.stored, 0)
        queue.retry()
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(queue.pending, 0)
        XCTAssertEqual(queue.stored, 1)
        XCTAssertEqual(queue.bytesStored, 2)
    }

    @MainActor
    func testRetryKeepsIdentityAndDiscardCannotCountLateAcknowledgement() async throws {
        var attempts: [Int] = []
        let saved = expectation(description: "saved after reconnect")
        let queue = UploadQueue { _, header in
            attempts.append(header.frame_id)
            if attempts.count == 1 { throw URLError(.networkConnectionLost) }
        }
        queue.acknowledged = { saved.fulfill() }
        XCTAssertTrue(queue.enqueue(Data([1]), header: header()))
        await fulfillment(of: [saved], timeout: 5)
        XCTAssertEqual(attempts, [2, 2])
        XCTAssertEqual(queue.stored, 1)
        let began = expectation(description: "send began")
        let pending = UploadQueue { _, _ in
            began.fulfill()
            try? await Task.sleep(for: .seconds(10))
        }
        XCTAssertTrue(pending.enqueue(Data([1]), header: header()))
        await fulfillment(of: [began], timeout: 2)
        pending.discard()
        await Task.yield()
        XCTAssertEqual(pending.pending, 0)
        XCTAssertEqual(pending.stored, 0)
        XCTAssertFalse(pending.enqueue(Data([1]), header: header()))
    }

    func testWindowBoundsAndRoomCodes() {
        var window = CaptureWindow()
        for _ in 0..<3 { XCTAssertTrue(window.reserve(100)) }
        XCTAssertFalse(window.reserve(100))
        window.complete(100)
        XCTAssertTrue(window.reserve(100))
        XCTAssertTrue(RoomAPI.validCode("ABCDEF12"))
        XCTAssertFalse(RoomAPI.validCode("../rooms"))
    }
}

extension TransportTests {
    func testGeographicAnchorRoundTripAndImprovement() throws {
        var value = header()
        let first = GeographicAnchor(latitude: 43.5, longitude: -79.5,
            horizontal_accuracy_m: 20, timestamp_unix_s: 100,
            pose_timestamp_s: 3, pose_time_offset_s: 0.1,
            camera_to_world: value.camera_to_world, heading: nil)
        value.geographic_anchor = first
        let encoded = try FramePacket(header: value, depth: [1], confidence: Data([2]), jpeg: Data()).encoded()
        let size = encoded[4..<8].enumerated().reduce(0) { $0 | Int($1.element) << ($1.offset * 8) }
        let restored = try JSONDecoder().decode(FrameHeader.self, from: encoded[8..<(8 + size)])
        XCTAssertEqual(restored.geographic_anchor?.longitude, -79.5)
        XCTAssertEqual(restored.camera_to_world, value.camera_to_world)
        var next = first
        next.timestamp_unix_s = 110
        XCTAssertFalse(next.improves(first))
        next.horizontal_accuracy_m = 10
        XCTAssertTrue(next.improves(first))
        next.timestamp_unix_s = 90
        XCTAssertFalse(next.improves(first))
        next.timestamp_unix_s = 110
        next.horizontal_accuracy_m = 30
        XCTAssertFalse(next.improves(first))
    }
}

extension TransportTests {
    func testGeographicCapabilityIsOptionalForOlderServers() throws {
        let old = Data(#"{"room_id":"ABCDEF12","name":"Room","closed":false,"frames_stored":0}"#.utf8)
        XCTAssertNil(try JSONDecoder().decode(Room.self, from: old).geography)
        let updated = Data(#"{"room_id":"ABCDEF12","name":"Room","closed":false,"frames_stored":0,"geography":{"schema_version":1,"anchors":[]}}"#.utf8)
        XCTAssertEqual(try JSONDecoder().decode(Room.self, from: updated).geography?.schema_version, 1)
    }
}
