import Foundation

/// QR codes carry only a room identity, never an alternate server address.
enum RoomLink {
    static func url(_ code: String) -> URL {
        URL(string: "htnroom://join/\(code)")!
    }

    static func code(from value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if RoomAPI.validCode(trimmed.uppercased()) { return trimmed.uppercased() }
        guard let url = URLComponents(string: trimmed), url.scheme == "htnroom",
              url.host == "join", url.query == nil, url.fragment == nil,
              url.user == nil, url.password == nil, url.port == nil else { return nil }
        let code = String(url.path.dropFirst()).uppercased()
        return RoomAPI.validCode(code) ? code : nil
    }
}
