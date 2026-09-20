import XCTest
@testable import HTNApp

final class AudioSpoolTests: XCTestCase {
    func testRestartReplayAndReceiptBounds() throws {
        let path = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: path) }
        let queue = try AudioSpool(directory: path)
        let first = Data(repeating: 7, count: 9600), second = Data(repeating: 9, count: 9600)
        try queue.append(first); try queue.append(second)
        XCTAssertEqual(try queue.chunk(0), first)
        let resumed = try AudioSpool(directory: path)
        XCTAssertEqual(resumed.requestID, queue.requestID)
        XCTAssertEqual(resumed.counts().next, 2)
        XCTAssertEqual(try resumed.chunk(1), second)
        XCTAssertThrowsError(try resumed.accept(3))
        XCTAssertEqual(resumed.counts().bytes, 19200)
        try resumed.accept(1)
        let restarted = try AudioSpool(directory: path)
        XCTAssertEqual(restarted.counts().acknowledged, 1)
        XCTAssertEqual(restarted.counts().next, 2)
        try restarted.accept(1) // Duplicate receipt is harmless.
        try restarted.accept(2)
        XCTAssertEqual(restarted.counts().bytes, 0)
        let emptyRestart = try AudioSpool(directory: path)
        XCTAssertEqual(emptyRestart.counts().next, 2)
        try emptyRestart.append(first)
        XCTAssertEqual(try emptyRestart.chunk(2), first)
        try emptyRestart.accept(3)
        try emptyRestart.removeIfEmpty()
        XCTAssertFalse(FileManager.default.fileExists(atPath: path.path))
    }
    func testBoundedOutageBufferDoesNotEvictAudio() throws {
        let path = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: path) }
        let queue = try AudioSpool(directory: path)
        let chunk = Data(repeating: 3, count: 24000)
        for _ in 0..<(AudioSpool.limit / chunk.count) { try queue.append(chunk) }
        XCTAssertThrowsError(try queue.append(chunk))
        XCTAssertEqual(queue.counts().bytes, AudioSpool.limit)
        XCTAssertEqual(try queue.chunk(0), chunk)
    }
}
