import Foundation

/// Used only on the serial capture queue. Bounds encoded camera work before it reaches the UI/uploader.
struct CaptureWindow {
    private var sizes: [Int] = []
    private(set) var bytes = 0
    var hasCapacity: Bool { sizes.count < 3 && bytes < 4_000_000 }

    mutating func reserve(_ size: Int) -> Bool {
        guard size > 0, hasCapacity, bytes + size <= 4_000_000 else { return false }
        sizes.append(size)
        bytes += size
        return true
    }

    mutating func complete(_ size: Int) {
        // Pending video can be superseded before the older in-flight frame finishes.
        guard let index = sizes.firstIndex(of: size) else { return }
        bytes -= sizes.remove(at: index)
    }
}
