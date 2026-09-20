import Foundation

/// ICE disconnection is temporary; failure is terminal. Do not destroy a call
/// before ICE has a chance to recover from a brief Wi-Fi interruption.
@MainActor
final class VoiceConnectionRecovery {
    private let grace: Duration
    private var timeout: Task<Void, Never>?
    init(grace: Duration = .seconds(5)) { self.grace = grace }

    @discardableResult
    func begin(expired: @escaping @MainActor () -> Void) -> Bool {
        guard timeout == nil else { return false }
        timeout = Task { [weak self, grace] in
            do { try await Task.sleep(for: grace) } catch { return }
            guard let self, !Task.isCancelled else { return }
            self.timeout = nil
            expired()
        }
        return true
    }

    func cancel() { timeout?.cancel(); timeout = nil }
}
