import XCTest
@testable import HTNApp

final class MediaUploadBudgetTests: XCTestCase {
    @MainActor func testFreshLossSlowsOnlyVideoAndStaleReportsDoNotAccumulate() {
        let budget = MediaUploadBudget(), owner = UUID()
        budget.begin(owner)
        budget.observe(id: "audio", timestamp: 1, lost: 0, rtt: 0.08)
        XCTAssertEqual(budget.spacing, 0.2)
        budget.observe(id: "audio", timestamp: 2, lost: 10, rtt: 0.08)
        XCTAssertEqual(budget.spacing, 0.4)
        for _ in 0..<1000 { budget.observe(id: "audio", timestamp: 2, lost: 10, rtt: 0.08) }
        XCTAssertEqual(budget.spacing, 0.4)
        budget.observe(id: "audio", timestamp: 3, lost: 10, rtt: 0.4)
        XCTAssertEqual(budget.spacing, 0.8)
        for time in 4...15 { budget.observe(id: "audio", timestamp: Double(time), lost: 10, rtt: 0.08) }
        XCTAssertEqual(budget.spacing, 0.2)
        budget.end(owner)
        XCTAssertEqual(budget.spacing, 0)
    }

    @MainActor func testCancelledVideoWaitAndOwnerIsolation() async throws {
        let budget = MediaUploadBudget(), first = UUID(), second = UUID()
        budget.begin(first); budget.begin(second)
        budget.end(first)
        XCTAssertEqual(budget.spacing, 0.2)
        try await budget.waitForTurn()
        let wait = Task { try await budget.waitForTurn() }
        wait.cancel()
        do { try await wait.value; XCTFail("Cancelled wait must not start an upload") }
        catch is CancellationError {} catch { XCTFail("Unexpected error: \(error)") }
        budget.end(second)
        XCTAssertEqual(budget.spacing, 0)
    }
}
