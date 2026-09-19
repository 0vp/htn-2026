import CoreVideo
import XCTest
@testable import HTNApp

final class CaptureBufferTests: XCTestCase {
    func testDepthAndConfidenceRespectRowStride() throws {
        var depth: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(nil, 3, 2, kCVPixelFormatType_DepthFloat32, nil, &depth), kCVReturnSuccess)
        let buffer = try XCTUnwrap(depth)
        CVPixelBufferLockBaseAddress(buffer, [])
        let pointer = try XCTUnwrap(CVPixelBufferGetBaseAddress(buffer))
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        for row in 0..<2 {
            let values = pointer.advanced(by: row * stride).assumingMemoryBound(to: Float.self)
            for column in 0..<3 { values[column] = Float(row * 3 + column) + 0.5 }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        XCTAssertEqual(PixelBuffers.depth(buffer), [0.5, 1.5, 2.5, 3.5, 4.5, 5.5])
        var confidence: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(nil, 3, 2, kCVPixelFormatType_OneComponent8, nil, &confidence), kCVReturnSuccess)
        let confidenceBuffer = try XCTUnwrap(confidence)
        CVPixelBufferLockBaseAddress(confidenceBuffer, [])
        let bytes = try XCTUnwrap(CVPixelBufferGetBaseAddress(confidenceBuffer))
        for row in 0..<2 {
            let values = bytes.advanced(by: row * CVPixelBufferGetBytesPerRow(confidenceBuffer)).assumingMemoryBound(to: UInt8.self)
            for column in 0..<3 { values[column] = UInt8(column) }
        }
        CVPixelBufferUnlockBaseAddress(confidenceBuffer, [])
        XCTAssertEqual(PixelBuffers.confidence(confidenceBuffer), Data([0, 1, 2, 0, 1, 2]))
    }
}
