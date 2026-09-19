import Foundation

/// Used only on the serial capture queue. Limits buffered data without lowering quality.
struct CaptureWindow {
    private var sizes: [Int] = []
    private(set) var bytes = 0
    var hasCapacity: Bool { sizes.count < 64 && bytes < 32_000_000 }

    mutating func reserve(_ size: Int) -> Bool {
        guard hasCapacity, bytes + size <= 32_000_000 else { return false }
        sizes.append(size)
        bytes += size
        return true
    }

    mutating func complete() {
        guard !sizes.isEmpty else { return }
        bytes -= sizes.removeFirst()
    }
}
