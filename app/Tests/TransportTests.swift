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
        for _ in 0..<64 { XCTAssertTrue(window.reserve(100)) }
        XCTAssertFalse(window.reserve(100))
        window.complete()
        XCTAssertTrue(window.reserve(100))
        XCTAssertTrue(RoomAPI.validCode("ABCDEF12"))
        XCTAssertFalse(RoomAPI.validCode("../rooms"))
    }
}
