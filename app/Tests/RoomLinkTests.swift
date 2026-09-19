import XCTest
import CoreImage
@testable import HTNApp

final class RoomLinkTests: XCTestCase {
    func testInvitesAreRoomIdentitiesOnly() {
        XCTAssertEqual(RoomLink.code(from: " abcdef12 \n"), "ABCDEF12")
        XCTAssertEqual(RoomLink.code(from: RoomLink.url("ABCDEF12").absoluteString), "ABCDEF12")
        for value in ["https://evil.test/ABCDEF12", "htnroom://join/ABCDEF12?server=evil",
                      "htnroom://other/ABCDEF12", "htnroom://join/ABCDEF12/extra", "../rooms",
                      "htnroom://user@join/ABCDEF12", "htnroom://join:123/ABCDEF12"] {
            XCTAssertNil(RoomLink.code(from: value), value)
        }
    }

    @MainActor
    func testRenderedQRCodeDecodesToInvite() throws {
        let invite = RoomLink.url("ABCDEF12").absoluteString
        let image = try XCTUnwrap(SyncSheet.makeQR(invite))
        let source = CIImage(cgImage: try XCTUnwrap(image.cgImage)).transformed(by: .init(scaleX: 10, y: 10))
        let detector = try XCTUnwrap(CIDetector(ofType: CIDetectorTypeQRCode,
            context: CIContext(options: [.useSoftwareRenderer: true]),
            options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]))
        let result = detector.features(in: source).first as? CIQRCodeFeature
        XCTAssertEqual(result?.messageString, invite)
    }

    @MainActor
    func testServerLeadershipDeterminesRole() throws {
        let data = Data(#"{"room_id":"ABCDEF12","name":"Room","closed":false,"frames_stored":0,"leader_device_id":"leader","devices":[]}"#.utf8)
        let room = try JSONDecoder().decode(Room.self, from: data)
        XCTAssertTrue(RoomSessionModel(room: room, device: "leader", api: RoomAPI()).isLeader)
        XCTAssertFalse(RoomSessionModel(room: room, device: "helper", api: RoomAPI()).isLeader)
        let legacy = try JSONDecoder().decode(Room.self, from: Data(#"{"room_id":"ABCDEF12","name":"Old","closed":false,"frames_stored":0}"#.utf8))
        XCTAssertFalse(RoomSessionModel(room: legacy, device: "helper", api: RoomAPI()).isLeader)
    }
}
