import AVFoundation
import SwiftUI
import VisionKit

struct RoomQRScanner: View {
    let found: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var allowed = false
    @State private var checked = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Group {
                if allowed, DataScannerViewController.isSupported, DataScannerViewController.isAvailable {
                    ScannerCamera(found: found, failed: { error = $0 })
                        .overlay(alignment: .bottom) {
                            Text(error ?? "Point at the QR code on the room’s main phone.")
                                .padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16)).padding()
                        }
                } else if checked {
                    ContentUnavailableView("Use a room code", systemImage: "qrcode",
                        description: Text("QR scanning is unavailable. Go back and enter the eight-character code shown on the other phone."))
                } else { ProgressView("Opening camera…") }
            }
            .navigationTitle("Scan room code").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .task {
                if DataScannerViewController.isSupported { allowed = await AVCaptureDevice.requestAccess(for: .video) }
                checked = true
            }
        }
    }
}

private struct ScannerCamera: UIViewControllerRepresentable {
    let found: (String) -> Void
    let failed: (String) -> Void
    func makeUIViewController(context: Context) -> ScannerController { ScannerController(found: found, failed: failed) }
    func updateUIViewController(_ controller: ScannerController, context: Context) {}
    static func dismantleUIViewController(_ controller: ScannerController, coordinator: ()) { controller.scanner.stopScanning() }
}

private final class ScannerController: UIViewController, DataScannerViewControllerDelegate {
    let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])],
        qualityLevel: .fast, recognizesMultipleItems: false, isHighFrameRateTrackingEnabled: false,
        isHighlightingEnabled: true)
    private let found: (String) -> Void
    private let failed: (String) -> Void
    private var delivered = false

    init(found: @escaping (String) -> Void, failed: @escaping (String) -> Void) {
        self.found = found; self.failed = failed
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    override func viewDidLoad() {
        super.viewDidLoad()
        scanner.delegate = self
        addChild(scanner)
        view.addSubview(scanner.view)
        scanner.view.frame = view.bounds
        scanner.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        scanner.didMove(toParent: self)
    }
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        do { try scanner.startScanning() } catch { failed("Camera unavailable. Use the room code instead.") }
    }
    func dataScanner(_ scanner: DataScannerViewController, didAdd addedItems: [RecognizedItem], allItems: [RecognizedItem]) {
        consume(addedItems)
    }
    func dataScanner(_ scanner: DataScannerViewController, didUpdate updatedItems: [RecognizedItem], allItems: [RecognizedItem]) {
        consume(updatedItems)
    }
    func dataScanner(_ scanner: DataScannerViewController, becameUnavailableWithError error: DataScannerViewController.ScanningUnavailable) {
        failed("Camera unavailable. Use the room code instead.")
    }
    private func consume(_ items: [RecognizedItem]) {
        guard !delivered else { return }
        for item in items {
            if case .barcode(let barcode) = item, let payload = barcode.payloadStringValue {
                guard let code = RoomLink.code(from: payload) else { failed("That QR code is not a room invite."); continue }
                delivered = true
                scanner.stopScanning()
                found(code)
                return
            }
        }
    }
}
