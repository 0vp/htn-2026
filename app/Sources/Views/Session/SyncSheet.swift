import CoreImage.CIFilterBuiltins
import SwiftUI

struct SyncSheet: View {
    @ObservedObject var session: RoomSessionModel
    @ObservedObject var scan: ScanModel
    @Environment(\.dismiss) private var dismiss
    @State private var qr: UIImage?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    Text("See more, together.").font(.title2.weight(.semibold))
                    Text("On another phone, open HTN and choose Scan QR to join.")
                        .foregroundStyle(.secondary).multilineTextAlignment(.center)
                    if let qr {
                        Image(uiImage: qr).interpolation(.none).resizable().scaledToFit()
                            .frame(maxWidth: 240).padding(20).background(.white, in: RoundedRectangle(cornerRadius: 24))
                            .accessibilityLabel("QR code for room \(session.room.id)")
                    }
                    Text(session.room.id).font(.title2.monospaced().weight(.semibold))
                        .textSelection(.enabled).accessibilityIdentifier("activeRoomCode")
                        .accessibilityValue(session.room.id)
                    ShareLink("Share room", item: RoomLink.url(session.room.id))
                    VStack(alignment: .leading, spacing: 16) {
                        Text("Joined phones").font(.headline)
                        ForEach(session.room.devices ?? []) { device in
                            HStack {
                                Image(systemName: "iphone")
                                Text(device.device_id == session.device ? "This iPhone" : device.name)
                                Spacer()
                                Text(device.device_id == session.room.leader_device_id ? "Leader" : "Contributor")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Text("Joining connects a phone to the room. The server aligns its view as frames arrive.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    DisclosureGroup("Streaming details") {
                        VStack(spacing: 12) {
                            LabeledContent("This phone uploaded", value: "\(scan.uploads.stored)")
                            LabeledContent("Waiting to upload", value: "\(scan.uploads.pending)")
                            if let status = session.processing {
                                LabeledContent("Room frames mapped", value: "\(status.mapped)")
                                LabeledContent("Room awaiting alignment", value: "\(status.awaiting_alignment)")
                            }
                            if let message = scan.uploads.message {
                                Text(message).font(.footnote).foregroundStyle(.secondary)
                                Button("Retry uploads") { scan.uploads.retry() }
                            }
                        }.padding(.top, 16).monospacedDigit()
                    }
                }.padding(24).frame(maxWidth: 520)
            }
            .navigationTitle("Sync phones").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task(id: session.room.id) { qr = Self.makeQR(RoomLink.url(session.room.id).absoluteString) }
        }.presentationDetents([.large]).presentationDragIndicator(.visible)
    }

    static func makeQR(_ payload: String) -> UIImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(payload.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage,
              let image = CIContext().createCGImage(output, from: output.extent) else { return nil }
        return UIImage(cgImage: image)
    }
}
