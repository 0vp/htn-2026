import SwiftUI

/// One shared world: the app joins it on launch and shows the session UI directly.
struct ContentView: View {
    @StateObject private var model = RoomsModel()
    @State private var displayedRoom: Room?

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Text("0_0").font(.system(size: 64, weight: .medium, design: .monospaced))
                .foregroundStyle(.tint).accessibilityHidden(true)
            Text("A room to see together.").font(.title2.weight(.semibold))
            if model.busy { ProgressView("Connecting…") }
            if let error = model.error {
                Text(error).foregroundStyle(.secondary).accessibilityIdentifier("roomError")
            }
            if !model.busy {
                Button { Task { await model.enterWorld() } } label: {
                    Label("Enter", systemImage: "arrow.right").frame(maxWidth: .infinity, minHeight: 36)
                }.buttonStyle(.borderedProminent)
            }
        }
        .padding(24).frame(maxWidth: 560)
        .task { await model.restore() }
        .onChange(of: model.selected) { _, room in displayedRoom = room }
        .fullScreenCover(item: $displayedRoom) { room in
            RoomSessionView(room: room, device: model.deviceID, api: model.api) { model.leave() }
        }
        .tint(.blue)
    }
}
