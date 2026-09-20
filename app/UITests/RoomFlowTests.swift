import XCTest

final class RoomFlowTests: XCTestCase {
    private let base = URL(string: "http://127.0.0.1:8897")!

    @MainActor
    func testAutoJoinsWorldAndReenters() async throws {
        var probe = URLRequest(url: base.appendingPathComponent("health"))
        probe.timeoutInterval = 2
        do { _ = try await URLSession.shared.data(for: probe) }
        catch { throw XCTSkip("Start the room API on port 8897 for UI integration tests.") }
        let app = XCUIApplication()
        app.launchEnvironment["HTN_TEST_SERVER"] = base.absoluteString
        app.launchArguments = ["--reset-room-for-testing"]
        app.launch()
        // Single shared room: the app joins on launch. Run the API with HTN_ROOM_ID=A0000001.
        XCTAssertTrue(app.buttons["Room actions"].waitForExistence(timeout: 15))
        save(app, "world")
        app.launchArguments = []
        app.launch()
        XCTAssertTrue(app.buttons["Room actions"].waitForExistence(timeout: 15))
        leave(app)
        app.buttons["Enter"].tap()
        XCTAssertTrue(app.buttons["Room actions"].waitForExistence(timeout: 15))
    }

    @MainActor private func leave(_ app: XCUIApplication) {
        app.buttons["Room actions"].tap()
        app.buttons["Leave room"].tap()
        XCTAssertTrue(app.buttons["Enter"].waitForExistence(timeout: 5))
    }

    private func save(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
