import XCTest

final class RoomFlowTests: XCTestCase {
    private let base = URL(string: "http://127.0.0.1:8897")!

    @MainActor
    func testLeaderSyncRestoreAndContributor() async throws {
        var probe = URLRequest(url: base.appendingPathComponent("health"))
        probe.timeoutInterval = 2
        do { _ = try await URLSession.shared.data(for: probe) }
        catch { throw XCTSkip("Start the room API on port 8897 for UI integration tests.") }
        let app = XCUIApplication()
        app.launchEnvironment["HTN_TEST_SERVER"] = base.absoluteString
        app.launchArguments = ["--reset-room-for-testing"]
        app.launch()
        XCTAssertTrue(app.buttons["Create room"].waitForExistence(timeout: 10))
        save(app, "rooms")
        app.buttons["Create room"].tap()
        app.textFields["roomName"].tap()
        app.textFields["roomName"].typeText("Robot room")
        app.buttons["Create"].tap()
        XCTAssertTrue(app.buttons["robotFace"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Room leader"].exists)
        app.buttons["voiceControls"].tap()
        let toggle = app.switches["connectCodex"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        toggle.tap()
        save(app, "voice-options")
        app.buttons["startVoice"].tap()
        XCTAssertTrue(app.staticTexts["voiceError"].waitForExistence(timeout: 10))
        save(app, "voice-unavailable")
        app.buttons["Done"].tap()
        app.buttons["robotFace"].tap()
        save(app, "leader-face")
        XCUIDevice.shared.orientation = .landscapeLeft
        let landscape = NSPredicate { _, _ in app.frame.width > app.frame.height }
        await fulfillment(of: [expectation(for: landscape, evaluatedWith: nil)], timeout: 5)
        try await Task.sleep(for: .seconds(1))
        XCTAssertTrue(app.buttons["Sync"].isHittable)
        save(app, "leader-landscape")
        XCUIDevice.shared.orientation = .portrait
        app.buttons["Sync"].tap()
        let codeElement = app.staticTexts["activeRoomCode"]
        XCTAssertTrue(codeElement.waitForExistence(timeout: 5))
        let code = try XCTUnwrap(codeElement.value as? String)
        XCTAssertEqual(code.count, 8)
        save(app, "sync")
        app.buttons["Done"].tap()
        app.terminate()
        app.launchArguments = []
        app.launch()
        XCTAssertTrue(app.buttons["robotFace"].waitForExistence(timeout: 15))
        leave(app)

        // A room created by another device must produce the contributor screen.
        var request = URLRequest(url: base.appendingPathComponent("v1/rooms"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data(#"{"name":"Other robot","device_id":"other-leader"}"#.utf8)
        let (data, _) = try await URLSession.shared.data(for: request)
        let room = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let otherCode = try XCTUnwrap(room["room_id"] as? String)
        app.buttons["Scan QR to join"].tap()
        app.textFields["roomCode"].tap()
        app.textFields["roomCode"].typeText(otherCode)
        app.buttons["Join room"].tap()
        XCTAssertTrue(app.staticTexts["Contributor"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["robotFace"].exists)
        save(app, "contributor")
        leave(app)
        app.buttons["Scan QR to join"].tap()
        app.buttons["Scan room QR"].tap()
        XCTAssertTrue(app.staticTexts["Use a room code"].waitForExistence(timeout: 5))
        save(app, "scanner-fallback")
        app.buttons["Cancel"].firstMatch.tap()
        app.textFields["roomCode"].tap()
        app.textFields["roomCode"].typeText("FFFFFFFF")
        app.buttons["Join room"].tap()
        XCTAssertTrue(app.staticTexts["roomError"].waitForExistence(timeout: 15))
        save(app, "missing-room")
    }

    @MainActor private func leave(_ app: XCUIApplication) {
        app.buttons["Room actions"].tap()
        app.buttons["Leave room"].tap()
        XCTAssertTrue(app.buttons["Create room"].waitForExistence(timeout: 5))
    }

    private func save(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
