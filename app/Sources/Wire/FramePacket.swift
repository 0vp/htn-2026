import Foundation

/// Intrinsics address the unrotated depth grid. Transform is column-major, in meters.
public struct FrameHeader: Codable {
    public var version = 1
    public var session_id: String
    public var epoch: Int
    public var frame_id: Int
    public var timestamp_s: Double
    public var tracking: String
    public var camera_convention: String
    public var depth_width: Int
    public var depth_height: Int
    public var rgb_width: Int
    public var rgb_height: Int
    public var rgb_bytes: Int
    public var fx: Float
    public var fy: Float
    public var cx: Float
    public var cy: Float
    public var camera_to_world: [Float]
    public var geographic_anchor: GeographicAnchor? = nil
}

public enum PacketError: Error {
    case invalidDimensions
    case invalidTransform
    case invalidConfidence
    case payloadTooLarge
}

public struct FramePacket {
    public var header: FrameHeader
    public var depth: [Float]
    public var confidence: Data
    public var jpeg: Data

    public func encoded() throws -> Data {
        let width = header.depth_width
        let height = header.depth_height
        guard header.version == 1, (1...1024).contains(width), (1...1024).contains(height),
              depth.count == width * height, confidence.count == depth.count,
              jpeg.count == header.rgb_bytes else {
            throw PacketError.invalidDimensions
        }
        guard header.camera_to_world.count == 16,
              header.camera_to_world.allSatisfy(\.isFinite) else {
            throw PacketError.invalidTransform
        }
        guard confidence.allSatisfy({ $0 <= 2 }) else {
            throw PacketError.invalidConfidence
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let metadata = try encoder.encode(header)
        guard metadata.count <= 16_384, jpeg.count <= 8_000_000 else {
            throw PacketError.payloadTooLarge
        }
        var packet = Data("R3D1".utf8)
        var count = UInt32(metadata.count).littleEndian
        withUnsafeBytes(of: &count) { packet.append(contentsOf: $0) }
        packet.append(metadata)
        let encodedDepth = depth.map { $0.bitPattern.littleEndian }
        encodedDepth.withUnsafeBytes { packet.append(contentsOf: $0) }
        packet.append(confidence)
        packet.append(jpeg)
        return packet
    }
}

/// Approximate WGS84 context only. All matrices retain ARKit local metre coordinates.
public struct GeographicAnchor: Codable {
    public var latitude: Double
    public var longitude: Double
    public var horizontal_accuracy_m: Double
    public var timestamp_unix_s: Double
    public var pose_timestamp_s: Double
    public var pose_time_offset_s: Double
    public var camera_to_world: [Float]
    public var heading: GeographicHeading?

    func improves(_ old: GeographicAnchor) -> Bool {
        guard timestamp_unix_s > old.timestamp_unix_s,
              horizontal_accuracy_m <= old.horizontal_accuracy_m else { return false }
        if let previous = old.heading {
            guard let next = heading,
                  next.accuracy_degrees <= previous.accuracy_degrees,
                  previous.reference != "true_north" || next.reference == "true_north"
            else { return false }
        }
        let betterHeading = heading.map { next in
            guard let previous = old.heading else { return true }
            return (next.accuracy_degrees < previous.accuracy_degrees &&
                    next.accuracy_degrees <= previous.accuracy_degrees * 0.8) ||
                (next.reference == "true_north" && previous.reference != "true_north")
        } ?? false
        return (horizontal_accuracy_m < old.horizontal_accuracy_m &&
                horizontal_accuracy_m <= old.horizontal_accuracy_m * 0.8) || betterHeading
    }
}

public struct GeographicHeading: Codable {
    public var degrees: Double
    public var accuracy_degrees: Double
    public var reference: String
    public var orientation = "landscape_right"
    public var timestamp_unix_s: Double
    public var pose_timestamp_s: Double
    public var pose_time_offset_s: Double
    public var camera_to_world: [Float]
    public var reference_direction_world: [Float]
}
