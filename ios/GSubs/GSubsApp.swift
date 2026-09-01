import SwiftUI

@main
struct GSubsApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .preferredColorScheme(.light)
                .statusBarHidden(model.videoURL != nil && !model.cues.isEmpty)
        }
    }
}

private struct RootView: View {
    @ObservedObject var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var restoring = true

    var body: some View {
        Group {
            if restoring {
                ProgressView("Σύνδεση με gsubs…")
            } else if model.isAuthenticated {
                StudioView(model: model)
            } else {
                LoginView(model: model)
            }
        }
        .task {
            await model.restoreSession()
            restoring = false
        }
        .onChange(of: scenePhase) { _, newPhase in
            guard newPhase != .active else { return }
            Task { await model.flushProjectDraft() }
        }
    }
}
