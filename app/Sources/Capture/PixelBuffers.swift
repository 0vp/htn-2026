#if canImport(ARKit) && os(iOS)
import ARKit
import CoreImage

enum PixelBuffers {
    static func depth(_ buffer: CVPixelBuffer) -> [Float] {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return [] }
        var result: [Float] = []
        result.reserveCapacity(width * height)
        for row in 0..<height {
            let pointer = base.advanced(by: row * rowBytes).assumingMemoryBound(to: Float.self)
            result.append(contentsOf: UnsafeBufferPointer(start: pointer, count: width))
        }
        return result
    }

    static func confidence(_ buffer: CVPixelBuffer) -> Data {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return Data() }
        var result = Data(capacity: width * height)
        for row in 0..<height {
            result.append(base.advanced(by: row * stride).assumingMemoryBound(to: UInt8.self),
                          count: width)
        }
        return result
    }
}
#endif
