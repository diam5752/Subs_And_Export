import SwiftUI

@main
struct GSubsApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .preferredColorScheme(.dark)
        }
    }
}

private struct RootView: View {
    @ObservedObject var model: AppModel
    @State private var restoring = true

    var body: some View {
        Group {
            if restoring {
                ProgressView("Σύνδεση με GSubs…")
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
    }
}
