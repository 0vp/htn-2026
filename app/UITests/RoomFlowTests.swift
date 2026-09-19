import XCTest

final class RoomFlowTests: XCTestCase {
    @MainActor
    func testCreateJoinAndMissingRoom() async throws {
        var probe = URLRequest(url: URL(string: "http://127.0.0.1:8895/health")!)
        probe.timeoutInterval = 2
        do { _ = try await URLSession.shared.data(for: probe) }
        catch { throw XCTSkip("Start the local backend on port 8895 for UI integration tests.") }
        let app = XCUIApplication()
        app.launchEnvironment["HTN_TEST_SERVER"] = "http://127.0.0.1:8895"
        app.launch()
        XCTAssertTrue(app.textFields["roomName"].waitForExistence(timeout: 10))
        app.textFields["roomName"].tap()
        app.textFields["roomName"].typeText("Living room")
        app.buttons["Create room"].tap()
        XCTAssertTrue(app.staticTexts["LiDAR required"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["Start capture"].isEnabled)
        let element = app.descendants(matching: .any).matching(identifier: "activeRoomCode").firstMatch
        let code = try XCTUnwrap(element.value as? String)
        XCTAssertEqual(code.count, 4)
        save(app, "capture")
        app.buttons["Done"].tap()
        XCTAssertTrue(app.textFields["roomCode"].waitForExistence(timeout: 5))
        app.textFields["roomCode"].tap()
        app.textFields["roomCode"].typeText(code)
        app.buttons["Join session"].tap()
        XCTAssertTrue(app.staticTexts["LiDAR required"].waitForExistence(timeout: 15))
        app.buttons["Done"].tap()
        app.textFields["roomCode"].tap()
        app.textFields["roomCode"].typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 4) + "FFFF")
        app.buttons["Join session"].tap()
        XCTAssertTrue(app.staticTexts["Room not found"].waitForExistence(timeout: 15))
        app.swipeUp()
        save(app, "missing-room")
    }

    private func save(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
