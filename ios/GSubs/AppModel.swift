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
    @Published private(set) var previewURL: URL?
    @Published private(set) var videoDuration = 0.0
    @Published var cues: [SubtitleCue] = [] {
        didSet { scheduleDraftSave() }
    }
    @Published var style = SubtitleStyle() {
        didSet { scheduleDraftSave() }
    }
    @Published private(set) var exportedURL: URL?
    @Published private(set) var phase: Phase = .idle
    @Published var errorMessage: String?
    @Published var noticeMessage: String?
    @Published private(set) var isAccountActionInFlight = false
    @Published private(set) var isSavingExport = false

    var isProjectOperationInFlight: Bool {
        [.readingVideo, .extractingAudio, .transcribing, .exporting].contains(phase)
            || isSavingExport
            || isAccountActionInFlight
    }

    private let api: any GSubsAPIClient
    private let audioExtractor: any AudioExtracting
    private let previewPreparer: any VideoPreviewPreparing
    private let videoExporter: any VideoExporting
    private let draftStore: any ProjectDraftStoring
    private let photoSaver = PhotoLibrarySaver()
    private var token: String?
    private var transcriptionKey = UUID().uuidString
    private var projectOperation = UUID()
    private var transcriptionTask: Task<Void, Never>?
    private var exportTask: Task<Void, Never>?
    private var draftSaveTask: Task<Void, Never>?
    private var activeDraft: ProjectDraft?
    private var draftRevision: UInt64 = 0
    private var isApplyingDraft = false
    private var draftPersistenceEnabled = true

    init(
        api: (any GSubsAPIClient)? = nil,
        audioExtractor: any AudioExtracting = AudioExtractor(),
        previewPreparer: any VideoPreviewPreparing = VideoPreviewPreparer(),
        videoExporter: (any VideoExporting)? = nil,
        draftStore: (any ProjectDraftStoring)? = nil,
        initialToken: String? = KeychainStore.readToken()
    ) {
        self.api = api ?? Self.defaultAPIClient()
        self.audioExtractor = audioExtractor
        self.previewPreparer = previewPreparer
        self.videoExporter = videoExporter ?? Self.defaultVideoExporter()
        self.draftStore = draftStore ?? ProjectDraftStore()
        LocalMediaStore.cleanupStaleMediaAtLaunch()
        #if DEBUG
            let testConfiguration = UITestConfiguration.current
            if testConfiguration.isEnabled {
                draftPersistenceEnabled = false
                guard testConfiguration.startsAuthenticated else { return }
                token = "ios-ui-test-token"
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
                if testConfiguration.startsWithVideo,
                    let demoURL = Self.makeUITestVideoCopy()
                {
                    videoURL = demoURL
                    previewURL = demoURL
                    videoDuration = 4
                    if testConfiguration.startsEditing {
                        cues = UITestAPIClient.sampleCues
                        phase = .editing
                    } else {
                        phase = .ready
                    }
                }
                return
            }
        #endif
        token = initialToken
    }

    private static func defaultAPIClient() -> any GSubsAPIClient {
        #if DEBUG
            let configuration = UITestConfiguration.current
            if configuration.isEnabled {
                return UITestAPIClient(configuration: configuration)
            }
        #endif
        return APIClient()
    }

    private static func defaultVideoExporter() -> any VideoExporting {
        #if DEBUG
            if UITestConfiguration.current.failsExport {
                return UITestFailingVideoExporter()
            }
            if UITestConfiguration.current.delaysExport {
                return UITestDelayedVideoExporter()
            }
        #endif
        return VideoExporter()
    }

    #if DEBUG
        private static func makeUITestVideoCopy() -> URL? {
            guard
                let bundledURL = Bundle.main.url(
                    forResource: "GSubsUITest",
                    withExtension: "mp4"
                ), let directory = try? LocalMediaStore.directory(named: "Videos")
            else {
                return nil
            }
            let destination =
                directory
                .appendingPathComponent("UITest-\(UUID().uuidString)")
                .appendingPathExtension("mp4")
            do {
                try FileManager.default.copyItem(at: bundledURL, to: destination)
                return destination
            } catch {
                return nil
            }
        }
    #endif

    func restoreSession() async {
        guard let token else { return }
        errorMessage = nil
        if draftPersistenceEnabled {
            lockPrivateProject()
            profile = nil
            points = nil
            isAuthenticated = false
            phase = .idle
        }
        do {
            let loadedProfile = try await api.profile(token: token)
            let loadedPoints = try await api.points(token: token)
            profile = loadedProfile
            points = loadedPoints
            isAuthenticated = true
            await restoreDraft(ownerUserID: loadedProfile.id)
        } catch {
            if isRejectedSession(error) {
                await clearLocalAccountState()
            } else {
                errorMessage = message(for: error)
            }
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
        await clearLocalAccountState()
        Self.deleteSessionToken()
        errorMessage = nil
        noticeMessage = nil
        if let tokenToRevoke { await api.logout(token: tokenToRevoke) }
    }

    func deleteAccount() async {
        guard let token, !isProjectOperationInFlight else { return }
        errorMessage = nil
        noticeMessage = nil
        isAccountActionInFlight = true
        defer { isAccountActionInFlight = false }

        do {
            try await api.deleteAccount(token: token)
            await clearLocalAccountState()
        } catch let error as AccountDeletionError {
            // After an ambiguous DELETE response, retaining the token/private
            // project is unsafe because the server may already have committed.
            await clearLocalAccountState()
            errorMessage = message(for: error)
        } catch {
            errorMessage = message(for: error)
        }
    }

    func accept(_ video: PickedVideo) async {
        guard isAuthenticated, let ownerUserID = profile?.id,
            !isProjectOperationInFlight
        else {
            try? FileManager.default.removeItem(at: video.url)
            return
        }
        errorMessage = nil
        noticeMessage = nil
        let purgeRevision = nextDraftRevision()
        lockPrivateProject()
        let operation = beginProjectOperation()
        do {
            try await draftStore.purge(ifNewerThan: purgeRevision)
        } catch {
            try? FileManager.default.removeItem(at: video.url)
            guard isCurrent(operation) else { return }
            errorMessage = message(for: error)
            return
        }
        guard isCurrent(operation) else {
            try? FileManager.default.removeItem(at: video.url)
            return
        }
        phase = .readingVideo
        var preparedPreviewURL: URL?
        do {
            let duration = try await audioExtractor.duration(of: video.url)
            preparedPreviewURL = try await previewPreparer.prepareIfNeeded(from: video.url)
            guard isCurrent(operation) else {
                try? FileManager.default.removeItem(at: video.url)
                if let preparedPreviewURL {
                    try? FileManager.default.removeItem(at: preparedPreviewURL)
                }
                return
            }
            let newTranscriptionKey = UUID().uuidString
            let restored = try await draftStore.commitProject(
                ownerUserID: ownerUserID,
                sourceURL: video.url,
                previewURL: preparedPreviewURL,
                duration: duration,
                transcriptionKey: newTranscriptionKey,
                revision: nextDraftRevision()
            )
            try? FileManager.default.removeItem(at: video.url)
            if let preparedPreviewURL {
                try? FileManager.default.removeItem(at: preparedPreviewURL)
            }
            guard isCurrent(operation) else { return }
            apply(restored)
            phase = .ready
        } catch {
            try? FileManager.default.removeItem(at: video.url)
            if let preparedPreviewURL {
                try? FileManager.default.removeItem(at: preparedPreviewURL)
            }
            guard isCurrent(operation) else { return }
            phase = .idle
            errorMessage = message(for: error)
        }
    }

    func generateSubtitles() {
        guard let token, let videoURL, !isProjectOperationInFlight else { return }
        errorMessage = nil
        noticeMessage = nil
        guard let points else {
            errorMessage = "Δεν ήταν δυνατή η επιβεβαίωση των διαθέσιμων credits. Δοκίμασε ξανά."
            return
        }
        guard points.reversalDebt <= 0 else {
            errorMessage = APIError.outstandingCreditReversalMessage
            return
        }
        guard points.balance >= 30 else {
            errorMessage = APIError.insufficientCreditsMessage
            return
        }
        guard points.paidBalance >= 30, points.aiSpendableBalance >= 30 else {
            errorMessage = APIError.insufficientPaidCreditsMessage
            return
        }
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
            let result = try await requestTranscription(
                audioURL: audioURL!,
                token: token,
                idempotencyKey: idempotencyKey,
                operation: operation
            )
            try Task.checkCancellation()
            guard isCurrent(operation) else { return }
            guard result.videoUploaded == false, result.serverMediaRetained == false else {
                throw APIError(status: 500, message: "Το API παραβίασε το local-media contract.")
            }
            cues = result.cues
            points = result.wallet
            phase = .editing
            do {
                try await persistDraftImmediately()
            } catch {
                errorMessage = message(for: error)
                return
            }
            noticeMessage = "Οι υπότιτλοι ήρθαν. Το βίντεο παρέμεινε στο iPhone."
        } catch {
            guard isCurrent(operation), !Task.isCancelled else { return }
            phase = .ready
            errorMessage = message(for: error)
        }
    }

    private func requestTranscription(
        audioURL: URL,
        token: String,
        idempotencyKey: String,
        operation: UUID
    ) async throws -> MobileTranscriptionResult {
        do {
            return try await api.transcribe(
                audioURL: audioURL,
                token: token,
                idempotencyKey: idempotencyKey
            )
        } catch let error as APIError
            where error.status == 409
            && error.message == "Previous transcription failed; try again"
        {
            try Task.checkCancellation()
            guard isCurrent(operation) else { throw CancellationError() }

            // A terminal server job can never succeed under the same key. Rotate
            // only for that explicit response; transport ambiguity keeps its key.
            let replacementKey = UUID().uuidString
            transcriptionKey = replacementKey
            do {
                try await persistDraftImmediately()
            } catch {
                transcriptionKey = idempotencyKey
                throw error
            }
            return try await api.transcribe(
                audioURL: audioURL,
                token: token,
                idempotencyKey: replacementKey
            )
        }
    }

    func exportVideo() {
        guard let videoURL, !cues.isEmpty, !isProjectOperationInFlight else { return }
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
        guard let exportedURL, !isProjectOperationInFlight else { return }
        let operation = projectOperation
        errorMessage = nil
        noticeMessage = nil
        isSavingExport = true
        defer { isSavingExport = false }
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
        let purgeRevision = nextDraftRevision()
        draftStore.lockImmediately(atRevision: purgeRevision)
        lockPrivateProject()
        Task { [draftStore] in
            try? await draftStore.purge(ifNewerThan: purgeRevision)
        }
        phase = .idle
        errorMessage = nil
        noticeMessage = nil
    }

    private func performAuth(_ operation: () async throws -> LoginResult) async {
        errorMessage = nil
        do {
            let result = try await operation()
            let loadedProfile = try await api.profile(token: result.accessToken)
            let loadedPoints = try await api.points(token: result.accessToken)
            try Self.saveSessionToken(result.accessToken)
            token = result.accessToken
            profile = loadedProfile
            points = loadedPoints
            isAuthenticated = true
            await restoreDraft(ownerUserID: loadedProfile.id)
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func lockPrivateProject() {
        invalidateProjectOperations()
        isApplyingDraft = true
        defer { isApplyingDraft = false }
        if activeDraft == nil {
            if let videoURL { try? FileManager.default.removeItem(at: videoURL) }
            if let previewURL, previewURL != videoURL {
                try? FileManager.default.removeItem(at: previewURL)
            }
        }
        if let exportedURL { try? FileManager.default.removeItem(at: exportedURL) }
        activeDraft = nil
        videoURL = nil
        previewURL = nil
        exportedURL = nil
        videoDuration = 0
        cues = []
        style = SubtitleStyle()
        phase = .idle
    }

    private func clearLocalAccountState() async {
        let purgeRevision = nextDraftRevision()
        draftStore.lockImmediately(atRevision: purgeRevision)
        lockPrivateProject()
        if let purgeRevision = try? await draftStore.purgeAll() {
            draftRevision = max(draftRevision, purgeRevision)
        }
        Self.deleteSessionToken()
        token = nil
        profile = nil
        points = nil
        isAuthenticated = false
        phase = .idle
    }

    private static func saveSessionToken(_ token: String) throws {
        #if DEBUG
            guard !UITestConfiguration.current.isEnabled else { return }
        #endif
        try KeychainStore.saveToken(token)
    }

    private static func deleteSessionToken() {
        #if DEBUG
            guard !UITestConfiguration.current.isEnabled else { return }
        #endif
        KeychainStore.deleteToken()
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
        draftSaveTask?.cancel()
        transcriptionTask = nil
        exportTask = nil
        draftSaveTask = nil
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

    func flushProjectDraft() async {
        do {
            try await persistDraftImmediately()
        } catch let error as ProjectDraftError where error == .staleRevision {
            return
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func restoreDraft(ownerUserID: String) async {
        guard draftPersistenceEnabled else { return }
        do {
            guard let restored = try await draftStore.restore(ownerUserID: ownerUserID) else {
                return
            }
            apply(restored)
        } catch {
            if let purgeRevision = try? await draftStore.purgeAll() {
                draftRevision = max(draftRevision, purgeRevision)
            }
            lockPrivateProject()
            phase = .idle
            errorMessage = message(for: error)
        }
    }

    private func apply(_ restored: RestoredProjectDraft) {
        isApplyingDraft = true
        defer { isApplyingDraft = false }
        activeDraft = restored.draft
        draftRevision = max(draftRevision, restored.draft.revision)
        videoURL = restored.sourceURL
        previewURL = restored.previewURL
        videoDuration = restored.draft.duration
        transcriptionKey = restored.draft.transcriptionKey
        cues = restored.draft.cues
        style = restored.draft.style
        exportedURL = nil
        phase = restored.draft.phase == .editing ? .editing : .ready
    }

    private func scheduleDraftSave() {
        guard !isApplyingDraft,
            draftPersistenceEnabled,
            isAuthenticated,
            let draft = updatedDraftSnapshot()
        else { return }
        activeDraft = draft
        draftSaveTask?.cancel()
        draftSaveTask = Task { [weak self, draftStore] in
            do {
                try await Task.sleep(for: .milliseconds(250))
                try Task.checkCancellation()
                try await draftStore.save(draft)
            } catch is CancellationError {
                return
            } catch let error as ProjectDraftError where error == .staleRevision {
                return
            } catch {
                guard self?.activeDraft?.revision == draft.revision else { return }
                self?.errorMessage = self?.message(for: error)
            }
        }
    }

    private func persistDraftImmediately() async throws {
        guard draftPersistenceEnabled, let draft = updatedDraftSnapshot() else { return }
        activeDraft = draft
        draftSaveTask?.cancel()
        draftSaveTask = nil
        try await draftStore.save(draft)
    }

    private func updatedDraftSnapshot() -> ProjectDraft? {
        guard let draft = activeDraft,
            draft.ownerUserID == profile?.id
        else { return nil }
        let durablePhase: ProjectDraft.DurablePhase = cues.isEmpty ? .ready : .editing
        return draft.updating(
            revision: nextDraftRevision(),
            cues: cues,
            style: style,
            transcriptionKey: transcriptionKey,
            phase: durablePhase
        )
    }

    private func nextDraftRevision() -> UInt64 {
        guard draftRevision < UInt64.max else { return draftRevision }
        draftRevision += 1
        return draftRevision
    }

    private func isRejectedSession(_ error: Error) -> Bool {
        guard let apiError = error as? APIError else { return false }
        return apiError.status == 401 || apiError.status == 403
    }

    private func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? "Κάτι πήγε στραβά. Δοκίμασε ξανά."
    }

}
