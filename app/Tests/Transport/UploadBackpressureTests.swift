import XCTest
@testable import HTNApp

final class UploadBackpressureTests: XCTestCase {
    private func header(_ id: Int) -> FrameHeader {
        FrameHeader(session_id: "backpressure", epoch: 1, frame_id: id, timestamp_s: Double(id),
            tracking: "normal", camera_convention: "arkit", depth_width: 1, depth_height: 1,
            rgb_width: 0, rgb_height: 0, rgb_bytes: 0, fx: 1, fy: 1, cx: 0, cy: 0,
            camera_to_world: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
    }

    @MainActor func testSlowUploadKeepsOnlyInFlightAndNewestFrame() async throws {
        let began = expectation(description: "first send began")
        let finished = expectation(description: "latest frame uploaded")
        var gate: CheckedContinuation<Void, Never>?
        var sent: [Int] = [], released = 0
        let queue = UploadQueue { _, frame in
            sent.append(frame.frame_id)
            if frame.frame_id == 0 {
                began.fulfill()
                await withCheckedContinuation { gate = $0 }
            }
        }
        queue.released = { _ in released += 1 }
        queue.acknowledged = { if sent.last == 10000 { finished.fulfill() } }
        let packet = Data(repeating: 1, count: 300_000)
        XCTAssertTrue(queue.enqueue(packet, header: header(0)))
        await fulfillment(of: [began], timeout: 2)
        for index in 1...10000 {
            XCTAssertTrue(queue.enqueue(packet, header: header(index)))
            XCTAssertLessThanOrEqual(queue.pending, 2)
            XCTAssertLessThanOrEqual(queue.bufferedBytes, 600_000)
        }
        XCTAssertEqual(queue.dropped, 9999)
        XCTAssertEqual(released, 9999)
        gate?.resume()
        await fulfillment(of: [finished], timeout: 2)
        XCTAssertEqual(sent, [0, 10000])
        XCTAssertEqual(queue.stored, 2)
        XCTAssertEqual(queue.bufferedBytes, 0)
        XCTAssertEqual(released, 10001)
    }

    func testOutOfOrderCameraReleaseKeepsExactByteAccounting() {
        var window = CaptureWindow()
        XCTAssertTrue(window.reserve(100))
        XCTAssertTrue(window.reserve(200))
        XCTAssertTrue(window.reserve(300))
        XCTAssertFalse(window.hasCapacity)
        window.complete(200) // Supersede pending frame before first upload finishes.
        XCTAssertEqual(window.bytes, 400)
        XCTAssertTrue(window.reserve(250))
        window.complete(100)
        window.complete(300)
        window.complete(250)
        XCTAssertEqual(window.bytes, 0)
        window.complete(250) // A late callback after draining must not underflow.
        XCTAssertEqual(window.bytes, 0)
    }
}
