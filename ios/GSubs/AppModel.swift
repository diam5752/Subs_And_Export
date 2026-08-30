import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    enum Phase: Equatable {
        case idle
        case readingVideo
        case ready
        case extractingAudio
        case transcribing
        case editing
        case exporting
        case exported
    }

    @Published private(set) var isAuthenticated = false
    @Published private(set) var profile: UserProfile?
    @Published private(set) var points: PointsBalance?
    @Published private(set) var videoURL: URL?
    @Published private(set) var videoDuration = 0.0
    @Published var cues: [SubtitleCue] = []
    @Published var style = SubtitleStyle()
    @Published private(set) var exportedURL: URL?
    @Published private(set) var phase: Phase = .idle
    @Published var errorMessage: String?
    @Published var noticeMessage: String?

    var isProjectOperationInFlight: Bool {
        [.extractingAudio, .transcribing, .exporting].contains(phase)
    }

    private let api: any GSubsAPIClient
    private let audioExtractor: any AudioExtracting
    private let videoExporter: any VideoExporting
    private let photoSaver = PhotoLibrarySaver()
    private var token: String?
    private var transcriptionKey = UUID().uuidString
    private var projectOperation = UUID()
    private var transcriptionTask: Task<Void, Never>?
    private var exportTask: Task<Void, Never>?

    init(
        api: any GSubsAPIClient = APIClient(),
        audioExtractor: any AudioExtracting = AudioExtractor(),
        videoExporter: any VideoExporting = VideoExporter(),
        initialToken: String? = KeychainStore.readToken()
    ) {
        self.api = api
        self.audioExtractor = audioExtractor
        self.videoExporter = videoExporter
        Self.removeStaleLocalMedia()
#if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--gsubs-ui-test-authenticated") {
            profile = UserProfile(
                id: "ios-ui-test",
                email: "ios-ui-test@gsubs.local",
                name: "iOS QA",
                provider: "local"
            )
            points = PointsBalance(
                balance: 100,
                paidBalance: 100,
                promotionalBalance: 0,
                reversalDebt: 0,
                aiSpendableBalance: 100
            )
            isAuthenticated = true
            return
        }
#endif
        token = initialToken
    }

    func restoreSession() async {
        guard let token else { return }
        do {
            profile = try await api.profile(token: token)
            points = try await api.points(token: token)
            isAuthenticated = true
        } catch {
            KeychainStore.deleteToken()
            self.token = nil
        }
    }

    func signIn(email: String, password: String) async {
        await performAuth {
            try await api.login(email: email, password: password)
        }
    }

    func register(name: String, email: String, password: String) async {
        await performAuth {
            try await api.register(email: email, password: password, name: name)
            return try await api.login(email: email, password: password)
        }
    }

    func signOut() async {
        let tokenToRevoke = token
        invalidateProjectOperations()
        cleanupProject()
        KeychainStore.deleteToken()
        token = nil
        profile = nil
        points = nil
        isAuthenticated = false
        phase = .idle
        errorMessage = nil
        noticeMessage = nil
        if let tokenToRevoke { await api.logout(token: tokenToRevoke) }
    }

    func accept(_ video: PickedVideo) async {
        guard isAuthenticated else {
            try? FileManager.default.removeItem(at: video.url)
            return
        }
        errorMessage = nil
        noticeMessage = nil
        let operation = beginProjectOperation()
        cleanupProject()
        phase = .readingVideo
        do {
            let duration = try await audioExtractor.duration(of: video.url)
            guard isCurrent(operation) else {
                try? FileManager.default.removeItem(at: video.url)
                return
            }
            videoDuration = duration
            videoURL = video.url
            transcriptionKey = UUID().uuidString
            phase = .ready
        } catch {
            try? FileManager.default.removeItem(at: video.url)
            guard isCurrent(operation) else { return }
            phase = .idle
            errorMessage = message(for: error)
        }
    }

    func generateSubtitles() {
        guard let token, let videoURL else { return }
        errorMessage = nil
        noticeMessage = nil
        let operation = beginProjectOperation()
        let idempotencyKey = transcriptionKey
        phase = .extractingAudio
        transcriptionTask = Task { [weak self] in
            await self?.runTranscription(
                videoURL: videoURL,
                token: token,
                idempotencyKey: idempotencyKey,
                operation: operation
            )
        }
    }

    private func runTranscription(
        videoURL: URL,
        token: String,
        idempotencyKey: String,
        operation: UUID
    ) async {
        var audioURL: URL?
        defer {
            if let audioURL { try? FileManager.default.removeItem(at: audioURL) }
            finishTranscription(operation)
        }
        do {
            audioURL = try await audioExtractor.extract(from: videoURL)
            try Task.checkCancellation()
            guard isCurrent(operation) else { return }
            phase = .transcribing
            let result = try await api.transcribe(
                audioURL: audioURL!,
                token: token,
                idempotencyKey: idempotencyKey
            )
            try Task.checkCancellation()
            guard isCurrent(operation) else { return }
            guard result.videoUploaded == false, result.serverMediaRetained == false else {
                throw APIError(status: 500, message: "Το API παραβίασε το local-media contract.")
            }
            let refreshedPoints = try? await api.points(token: token)
            try Task.checkCancellation()
            guard isCurrent(operation) else { return }
            cues = result.cues
            if let refreshedPoints { points = refreshedPoints }
            phase = .editing
            noticeMessage = "Οι υπότιτλοι ήρθαν. Το βίντεο παρέμεινε στο iPhone."
        } catch {
            guard isCurrent(operation), !Task.isCancelled else { return }
            phase = .ready
            errorMessage = message(for: error)
        }
    }

    func exportVideo() {
        guard let videoURL, !cues.isEmpty else { return }
        errorMessage = nil
        noticeMessage = nil
        let cuesToExport = cues
        let styleToExport = style
        let operation = beginProjectOperation()
        phase = .exporting
        exportTask = Task { [weak self] in
            await self?.runExport(
                videoURL: videoURL,
                cues: cuesToExport,
                style: styleToExport,
                operation: operation
            )
        }
    }

    private func runExport(
        videoURL: URL,
        cues: [SubtitleCue],
        style: SubtitleStyle,
        operation: UUID
    ) async {
        var candidateURL: URL?
        defer {
            if !isCurrent(operation), let candidateURL {
                try? FileManager.default.removeItem(at: candidateURL)
            }
            finishExport(operation)
        }
        do {
            candidateURL = try await videoExporter.export(
                videoURL: videoURL,
                cues: cues,
                style: style
            )
            try Task.checkCancellation()
            guard isCurrent(operation), let candidateURL else { return }
            if let exportedURL { try? FileManager.default.removeItem(at: exportedURL) }
            exportedURL = candidateURL
            phase = .exported
            noticeMessage = "Το MP4 δημιουργήθηκε και ελέγχθηκε τοπικά."
        } catch {
            guard isCurrent(operation), !Task.isCancelled else { return }
            phase = .editing
            errorMessage = message(for: error)
        }
    }

    func saveExportToPhotos() async {
        guard let exportedURL else { return }
        let operation = projectOperation
        do {
            try await photoSaver.save(videoURL: exportedURL)
            guard isCurrent(operation), self.exportedURL == exportedURL else { return }
            noticeMessage = "Αποθηκεύτηκε στις Φωτογραφίες."
        } catch {
            guard isCurrent(operation), self.exportedURL == exportedURL else { return }
            errorMessage = message(for: error)
        }
    }

    func resetProject() {
        invalidateProjectOperations()
        cleanupProject()
        phase = .idle
        errorMessage = nil
        noticeMessage = nil
    }

    private func performAuth(_ operation: () async throws -> LoginResult) async {
        errorMessage = nil
        do {
            let result = try await operation()
            try KeychainStore.saveToken(result.accessToken)
            token = result.accessToken
            profile = try await api.profile(token: result.accessToken)
            points = try await api.points(token: result.accessToken)
            isAuthenticated = true
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func cleanupProject() {
        if let videoURL { try? FileManager.default.removeItem(at: videoURL) }
        if let exportedURL { try? FileManager.default.removeItem(at: exportedURL) }
        videoURL = nil
        exportedURL = nil
        videoDuration = 0
        cues = []
        style = SubtitleStyle()
    }

    @discardableResult
    private func beginProjectOperation() -> UUID {
        invalidateProjectOperations()
        return projectOperation
    }

    private func invalidateProjectOperations() {
        projectOperation = UUID()
        transcriptionTask?.cancel()
        exportTask?.cancel()
        transcriptionTask = nil
        exportTask = nil
    }

    private func isCurrent(_ operation: UUID) -> Bool {
        operation == projectOperation && isAuthenticated && !Task.isCancelled
    }

    private func finishTranscription(_ operation: UUID) {
        guard operation == projectOperation else { return }
        transcriptionTask = nil
    }

    private func finishExport(_ operation: UUID) {
        guard operation == projectOperation else { return }
        exportTask = nil
    }

    private func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? "Κάτι πήγε στραβά. Δοκίμασε ξανά."
    }

    private static func removeStaleLocalMedia() {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("GSubs", isDirectory: true)
        try? FileManager.default.removeItem(at: root)
    }
}
