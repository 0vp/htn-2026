import Foundation

/// Disk-backed ordered PCM queue. Only a server receipt releases stored bytes.
/// Used on the audio worker queue or under this lock; never from the render callback.
final class AudioSpool: @unchecked Sendable {
    private let lock = NSRecursiveLock()
    let directory: URL
    private(set) var next = 0
    private(set) var acknowledged = 0
    let requestID: String
    private var bytes = 0
    static let limit = 48_000 * 300

    init(directory: URL) throws {
        self.directory = directory
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let identity = directory.appendingPathComponent("identity")
        if let existing = try? String(contentsOf: identity, encoding: .utf8) { requestID = existing }
        else { requestID = UUID().uuidString; try Data(requestID.utf8).write(to: identity, options: .atomic) }
        let sequences = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "pcm" }.compactMap { Int($0.deletingPathExtension().lastPathComponent) }.sorted()
        let savedNext = (try? String(contentsOf: directory.appendingPathComponent("next"), encoding: .utf8)).flatMap(Int.init) ?? 0
        next = max(savedNext, (sequences.last.map { $0 + 1 }) ?? 0)
        acknowledged = sequences.first ?? next
        for seq in sequences { bytes += try Data(contentsOf: file(seq)).count }
        var resource = directory
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try resource.setResourceValues(values)
    }
    func append(_ pcm: Data) throws {
        lock.lock(); defer { lock.unlock() }
        guard !pcm.isEmpty, pcm.count % 2 == 0, pcm.count <= 24_000,
              bytes + pcm.count <= Self.limit else {
            throw APIError(message: "Audio buffer full. Recording stopped; pending audio is retained.")
        }
        let target = file(next)
        try pcm.write(to: target, options: [.atomic, .completeFileProtectionUnlessOpen])
        // An atomic rename prevents partially visible chunks. Server acknowledgments
        // provide the durable remote copy before these local files are removed.
        next += 1; bytes += pcm.count
        try Data(String(next).utf8).write(to: directory.appendingPathComponent("next"), options: .atomic)
    }
    func chunk(_ seq: Int) throws -> Data? {
        lock.lock(); defer { lock.unlock() }
        guard seq >= acknowledged, seq < next else { return nil }
        return try Data(contentsOf: file(seq))
    }
    func accept(_ sequence: Int) throws {
        lock.lock(); defer { lock.unlock() }
        guard sequence >= acknowledged, sequence <= next else {
            throw APIError(message: "Invalid audio receipt. Local audio retained.")
        }
        for seq in acknowledged..<sequence {
            let path = file(seq)
            let size = (try FileManager.default.attributesOfItem(atPath: path.path)[.size] as? NSNumber)?.intValue ?? 0
            try FileManager.default.removeItem(at: path)
            bytes -= size
            acknowledged = seq + 1
        }
    }
    func counts() -> (next: Int, acknowledged: Int, bytes: Int) {
        lock.lock(); defer { lock.unlock() }
        return (next, acknowledged, bytes)
    }
    func removeIfEmpty() throws {
        lock.lock(); defer { lock.unlock() }
        guard acknowledged == next else { return }
        try FileManager.default.removeItem(at: directory)
    }
    private func file(_ seq: Int) -> URL { directory.appendingPathComponent("\(seq).pcm") }
}
