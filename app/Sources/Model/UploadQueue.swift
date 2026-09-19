import Combine
import Foundation

@MainActor
final class UploadQueue: ObservableObject {
    struct Item { let data: Data; let header: FrameHeader }
    @Published private(set) var pending = 0
    @Published private(set) var stored = 0
    @Published private(set) var bytesStored = 0
    @Published private(set) var message: String?
    private var items: [Item] = []
    private var worker: Task<Void, Never>?
    private var bufferedBytes = 0
    private var blocked = false
    private var closed = false
    private let send: (Data, FrameHeader) async throws -> Void
    var acknowledged: () -> Void = {}
    var failed: () -> Void = {}

    init(send: @escaping (Data, FrameHeader) async throws -> Void) { self.send = send }

    func enqueue(_ data: Data, header: FrameHeader) -> Bool {
        guard !closed, items.count < 64, bufferedBytes + data.count <= 32_000_000 else { return false }
        items.append(Item(data: data, header: header))
        bufferedBytes += data.count
        pending = items.count
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
                    message = nil
                    delay = 1
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
        items.removeAll()
        bufferedBytes = 0
        pending = 0
    }
}
