import Combine
import Foundation

@MainActor
final class UploadQueue: ObservableObject {
    struct Item { let data: Data; let header: FrameHeader }
    @Published private(set) var pending = 0
    @Published private(set) var dropped = 0
    @Published private(set) var stored = 0
    @Published private(set) var bytesStored = 0
    @Published private(set) var message: String?
    private var items: [Item] = []
    private var worker: Task<Void, Never>?
    private(set) var bufferedBytes = 0
    private var blocked = false
    private var closed = false
    private let send: (Data, FrameHeader) async throws -> Void
    var acknowledged: () -> Void = {}
    var released: (Int) -> Void = { _ in }
    var failed: () -> Void = {}

    init(send: @escaping (Data, FrameHeader) async throws -> Void) {
        self.send = send
        recordMetrics()
    }

    private func recordMetrics() {
        MediaUploadBudget.shared.recordVideo(pending: pending, bytes: bufferedBytes,
                                             dropped: dropped, uploadedBytes: bytesStored)
    }

    func enqueue(_ data: Data, header: FrameHeader) -> Bool {
        // Preserve the in-flight frame for idempotent retries. Replace only unsent
        // camera work; voice never enters this queue.
        let replaced = items.count > 1 ? items.last : nil
        guard !closed, data.count <= 4_000_000,
              bufferedBytes - (replaced?.data.count ?? 0) + data.count <= 4_000_000 else { return false }
        if let replaced {
            items.removeLast()
            bufferedBytes -= replaced.data.count
            dropped += 1
            released(replaced.data.count)
        }
        items.append(Item(data: data, header: header))
        bufferedBytes += data.count
        pending = items.count
        recordMetrics()
        if !blocked { pump() }
        return true
    }

    func retry() {
        blocked = false
        pump()
    }

    private func pump() {
        guard !closed, worker == nil, !items.isEmpty else { return }
        worker = Task { [weak self] in
            guard let self else { return }
            var delay = 1
            while !Task.isCancelled, let next = items.first {
                do {
                    try await send(next.data, next.header)
                    guard !Task.isCancelled else { break }
                    items.removeFirst()
                    bufferedBytes -= next.data.count
                    pending = items.count
                    stored += 1
                    bytesStored += next.data.count
                    recordMetrics()
                    message = nil
                    delay = 1
                    released(next.data.count)
                    acknowledged()
                } catch {
                    guard !Task.isCancelled else { break }
                    message = "\(error.localizedDescription) Keep the app open to finish uploading."
                    if let failure = error as? StreamFailure, !failure.retryable {
                        blocked = true
                        failed()
                        break
                    }
                    do { try await Task.sleep(for: .seconds(delay)) } catch { break }
                    delay = min(delay * 2, 8)
                }
            }
            worker = nil
        }
    }

    func discard() {
        closed = true
        worker?.cancel()
        // Keep the cancelled worker until it exits, so no second sender can race it.
        let remaining = items
        items.removeAll()
        bufferedBytes = 0
        pending = 0
        recordMetrics()
        remaining.forEach { released($0.data.count) }
    }
}
