import Foundation
import XCTest

@testable import GSubs

@MainActor
final class AppModelRaceTests: XCTestCase {
    func testResetRejectsLateTranscriptionResult() async throws {
        let api = ControlledAPIClient()
        let audioURL = temporaryFile(named: "audio.m4a")
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: audioURL),
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "source.mp4")
        await model.accept(PickedVideo(url: videoURL))

        model.generateSubtitles()
        try await waitUntil { await api.transcriptionStarted() }
        XCTAssertTrue(model.isProjectOperationInFlight)
        model.resetProject()
        await api.completeTranscription(with: transcriptionResult)
        try await waitUntil { !FileManager.default.fileExists(atPath: audioURL.path) }

        XCTAssertEqual(model.phase, .idle)
        XCTAssertFalse(model.isProjectOperationInFlight)
        XCTAssertNil(model.videoURL)
        XCTAssertTrue(model.cues.isEmpty)
        XCTAssertEqual(model.points?.balance, 100)
        XCTAssertNil(model.noticeMessage)
    }

    func testSignOutRejectsLateTranscriptionResult() async throws {
        let api = ControlledAPIClient()
        let audioURL = temporaryFile(named: "logout-audio.m4a")
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: audioURL),
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "logout-source.mp4")
        await model.accept(PickedVideo(url: videoURL))

        model.generateSubtitles()
        try await waitUntil { await api.transcriptionStarted() }
        XCTAssertTrue(model.isProjectOperationInFlight)
        await model.signOut()
        await api.completeTranscription(with: transcriptionResult)
        try await waitUntil { !FileManager.default.fileExists(atPath: audioURL.path) }

        XCTAssertFalse(model.isAuthenticated)
        XCTAssertEqual(model.phase, .idle)
        XCTAssertFalse(model.isProjectOperationInFlight)
        XCTAssertNil(model.videoURL)
        XCTAssertTrue(model.cues.isEmpty)
        XCTAssertNil(model.points)
        XCTAssertNil(model.noticeMessage)
    }

    func testTerminalTranscriptionConflictRetriesOnceWithANewKeyAndCleansAudio() async throws {
        let audioURL = temporaryFile(named: "terminal-retry-audio.m4a")
        let expectedResult = transcriptionResult
        let api = ControlledAPIClient(transcriptionResponses: [
            .apiError(status: 409, message: "Previous transcription failed; try again"),
            .success(expectedResult),
        ])
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: audioURL),
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "terminal-retry-source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        defer { model.resetProject() }

        model.generateSubtitles()
        try await waitUntil { model.phase == .editing }
        try await waitUntil { !FileManager.default.fileExists(atPath: audioURL.path) }

        let keys = await api.transcriptionKeysReceived()
        XCTAssertEqual(keys.count, 2)
        XCTAssertNotEqual(keys[0], keys[1])
        XCTAssertEqual(model.cues, expectedResult.cues)
        XCTAssertFalse(model.isProjectOperationInFlight)
        XCTAssertNil(model.errorMessage)
    }

    func testSuccessfulTranscriptionAppliesTheResponseWalletWithoutRefreshing() async throws {
        let response = MobileTranscriptionResult(
            requestId: "wallet-result",
            durationSeconds: 1,
            creditsCharged: 30,
            balance: 70,
            paidBalance: 42,
            promotionalBalance: 28,
            reversalDebt: 0,
            aiSpendableBalance: 42,
            videoUploaded: false,
            serverMediaRetained: false,
            cues: [SubtitleCue(start: 0, end: 1, text: "WALLET", words: [])]
        )
        let api = ControlledAPIClient(transcriptionResponses: [.success(response)])
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(
                audioURL: temporaryFile(named: "wallet-result-audio.m4a")
            ),
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "wallet-result-source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        defer { model.resetProject() }

        model.generateSubtitles()
        try await waitUntil { model.phase == .editing }

        let pointsRequestCount = await api.pointsRequestCount()
        XCTAssertEqual(model.points, response.wallet)
        XCTAssertEqual(pointsRequestCount, 1)
    }

    func testTranscriptionPreflightRequiresThirtyAISpendableCredits() async throws {
        let unavailableWallet = PointsBalance(
            balance: 100,
            paidBalance: 0,
            promotionalBalance: 100,
            reversalDebt: 0,
            aiSpendableBalance: 0
        )
        let api = ControlledAPIClient(pointsBalance: unavailableWallet)
        let extractor = CountingAudioExtractor(
            audioURL: temporaryFile(named: "preflight-audio.m4a")
        )
        let model = AppModel(
            api: api,
            audioExtractor: extractor,
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "preflight-source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        defer { model.resetProject() }

        model.generateSubtitles()

        let extractionCount = await extractor.extractionCount()
        let transcriptionStarted = await api.transcriptionStarted()
        XCTAssertEqual(model.phase, .ready)
        XCTAssertEqual(model.errorMessage, APIError.insufficientPaidCreditsMessage)
        XCTAssertEqual(extractionCount, 0)
        XCTAssertFalse(transcriptionStarted)
    }

    func testTranscriptionPreflightExplainsOutstandingReversalBeforeExtraction() async throws {
        let blockedWallet = PointsBalance(
            balance: 100,
            paidBalance: 80,
            promotionalBalance: 20,
            reversalDebt: 15,
            aiSpendableBalance: 0
        )
        let api = ControlledAPIClient(pointsBalance: blockedWallet)
        let extractor = CountingAudioExtractor(
            audioURL: temporaryFile(named: "reversal-preflight-audio.m4a")
        )
        let model = AppModel(
            api: api,
            audioExtractor: extractor,
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "reversal-preflight-source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        defer { model.resetProject() }

        model.generateSubtitles()

        let extractionCount = await extractor.extractionCount()
        let transcriptionStarted = await api.transcriptionStarted()
        XCTAssertEqual(model.phase, .ready)
        XCTAssertEqual(model.errorMessage, APIError.outstandingCreditReversalMessage)
        XCTAssertEqual(extractionCount, 0)
        XCTAssertFalse(transcriptionStarted)
    }

    func testNetworkTranscriptionFailureKeepsTheIdempotencyKey() async throws {
        let audioURL = temporaryFile(named: "network-retry-audio.m4a")
        let api = ControlledAPIClient(transcriptionResponses: [
            .networkError,
            .networkError,
        ])
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: audioURL),
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "network-retry-source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        defer { model.resetProject() }

        model.generateSubtitles()
        try await waitUntil { await api.transcriptionRequestCount() == 1 && model.phase == .ready }
        model.generateSubtitles()
        try await waitUntil { await api.transcriptionRequestCount() == 2 && model.phase == .ready }

        let keys = await api.transcriptionKeysReceived()
        XCTAssertEqual(keys.count, 2)
        XCTAssertEqual(keys[0], keys[1])
    }

    func testOtherTranscriptionConflictKeepsTheIdempotencyKey() async throws {
        let audioURL = temporaryFile(named: "other-conflict-audio.m4a")
        let api = ControlledAPIClient(transcriptionResponses: [
            .apiError(status: 409, message: "Transcription is already in progress"),
            .apiError(status: 409, message: "Transcription is already in progress"),
        ])
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: audioURL),
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "other-conflict-source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        defer { model.resetProject() }

        model.generateSubtitles()
        try await waitUntil { await api.transcriptionRequestCount() == 1 && model.phase == .ready }
        XCTAssertEqual(model.errorMessage, APIError.transcriptionInProgressMessage)
        model.generateSubtitles()
        try await waitUntil { await api.transcriptionRequestCount() == 2 && model.phase == .ready }

        let keys = await api.transcriptionKeysReceived()
        XCTAssertEqual(keys.count, 2)
        XCTAssertEqual(keys[0], keys[1])
    }

    func testResetDeletesLateExportAndKeepsProjectIdle() async throws {
        let api = ControlledAPIClient()
        let exporter = ControlledVideoExporter()
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: temporaryURL(named: "unused.m4a")),
            previewPreparer: StubVideoPreviewPreparer(),
            videoExporter: exporter,
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        model.cues = [SubtitleCue(start: 0, end: 1, text: "LATE", words: [])]
        let lateExportURL = temporaryFile(named: "late-export.mp4")

        model.exportVideo()
        try await waitUntil { await exporter.exportStarted() }
        XCTAssertTrue(model.isProjectOperationInFlight)
        model.resetProject()
        await exporter.completeExport(with: lateExportURL)
        try await waitUntil { !FileManager.default.fileExists(atPath: lateExportURL.path) }

        XCTAssertEqual(model.phase, .idle)
        XCTAssertFalse(model.isProjectOperationInFlight)
        XCTAssertNil(model.exportedURL)
        XCTAssertNil(model.noticeMessage)
    }

    func testResetRejectsLatePreviewAndDeletesBothFiles() async throws {
        let api = ControlledAPIClient()
        let preparer = ControlledVideoPreviewPreparer()
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: temporaryURL(named: "unused.m4a")),
            previewPreparer: preparer,
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "preview-source.mp4")
        let previewURL = temporaryFile(named: "preview-proxy.mp4")

        let acceptTask = Task { await model.accept(PickedVideo(url: videoURL)) }
        try await waitUntil { await preparer.preparationStarted() }
        model.resetProject()
        await preparer.completePreparation(with: previewURL)
        await acceptTask.value

        XCTAssertEqual(model.phase, .idle)
        XCTAssertNil(model.videoURL)
        XCTAssertNil(model.previewURL)
        XCTAssertFalse(FileManager.default.fileExists(atPath: videoURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: previewURL.path))
    }

    func testUncertainAccountDeletionClearsTheLocalSessionAndPrivateProject() async throws {
        KeychainStore.deleteToken()
        defer { KeychainStore.deleteToken() }
        let api = ControlledAPIClient(accountDeletionBehavior: .confirmationUnavailable)
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: temporaryURL(named: "unused.m4a")),
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "uncertain-delete-source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        model.cues = [SubtitleCue(start: 0, end: 1, text: "PRIVATE", words: [])]

        await model.deleteAccount()
        await model.restoreSession()

        XCTAssertFalse(model.isAuthenticated)
        XCTAssertEqual(model.phase, .idle)
        XCTAssertNil(model.profile)
        XCTAssertNil(model.points)
        XCTAssertNil(model.videoURL)
        XCTAssertNil(model.previewURL)
        XCTAssertTrue(model.cues.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: videoURL.path))
        XCTAssertNil(KeychainStore.readToken())
        XCTAssertEqual(
            model.errorMessage,
            AccountDeletionError.confirmationUnavailable.errorDescription
        )
    }

    func testExplicitAccountDeletionRejectionKeepsTheSessionAndPrivateProject() async throws {
        let api = ControlledAPIClient(accountDeletionBehavior: .rejected)
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: temporaryURL(named: "unused.m4a")),
            previewPreparer: StubVideoPreviewPreparer(),
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let videoURL = temporaryFile(named: "rejected-delete-source.mp4")
        await model.accept(PickedVideo(url: videoURL))
        let persistentVideoURL = try XCTUnwrap(model.videoURL)
        defer { model.resetProject() }

        await model.deleteAccount()

        XCTAssertTrue(model.isAuthenticated)
        XCTAssertEqual(model.phase, .ready)
        XCTAssertEqual(model.videoURL, persistentVideoURL)
        XCTAssertTrue(FileManager.default.fileExists(atPath: persistentVideoURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: videoURL.path))
        XCTAssertEqual(model.errorMessage, "Deletion is blocked")
        XCTAssertFalse(model.isAccountActionInFlight)
        XCTAssertFalse(model.isProjectOperationInFlight)
    }

    func testAccountDeletionBlocksProjectMutationsUntilItCompletes() async throws {
        let api = ControlledAPIClient(accountDeletionBehavior: .controlled)
        let exporter = ControlledVideoExporter()
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: temporaryURL(named: "blocked-audio.m4a")),
            previewPreparer: StubVideoPreviewPreparer(),
            videoExporter: exporter,
            draftStore: isolatedDraftStore(),
            initialToken: "test-token"
        )
        await model.restoreSession()
        let currentVideoURL = temporaryFile(named: "current-private-project.mp4")
        await model.accept(PickedVideo(url: currentVideoURL))
        let persistentVideoURL = try XCTUnwrap(model.videoURL)
        let currentCues = [SubtitleCue(start: 0, end: 1, text: "PRIVATE", words: [])]
        model.cues = currentCues

        let deletion = Task { await model.deleteAccount() }
        try await waitUntil { await api.accountDeletionStarted() }
        XCTAssertTrue(model.isAccountActionInFlight)
        XCTAssertTrue(model.isProjectOperationInFlight)

        await model.deleteAccount()
        model.generateSubtitles()
        model.exportVideo()
        let rejectedVideoURL = temporaryFile(named: "rejected-new-project.mp4")
        await model.accept(PickedVideo(url: rejectedVideoURL))

        XCTAssertEqual(model.phase, .ready)
        XCTAssertEqual(model.videoURL, persistentVideoURL)
        XCTAssertEqual(model.cues, currentCues)
        XCTAssertTrue(FileManager.default.fileExists(atPath: persistentVideoURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: currentVideoURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: rejectedVideoURL.path))
        let deletionRequestCount = await api.accountDeletionRequestCount()
        let transcriptionStarted = await api.transcriptionStarted()
        let exportStarted = await exporter.exportStarted()
        XCTAssertEqual(deletionRequestCount, 1)
        XCTAssertFalse(transcriptionStarted)
        XCTAssertFalse(exportStarted)

        await api.completeAccountDeletion()
        await deletion.value

        XCTAssertFalse(model.isAuthenticated)
        XCTAssertFalse(model.isAccountActionInFlight)
        XCTAssertFalse(model.isProjectOperationInFlight)
        XCTAssertEqual(model.phase, .idle)
        XCTAssertNil(model.videoURL)
        XCTAssertTrue(model.cues.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: persistentVideoURL.path))
    }

    private var transcriptionResult: MobileTranscriptionResult {
        MobileTranscriptionResult(
            requestId: "late-result",
            durationSeconds: 1,
            creditsCharged: 30,
            balance: 70,
            paidBalance: 50,
            promotionalBalance: 20,
            reversalDebt: 0,
            aiSpendableBalance: 50,
            videoUploaded: false,
            serverMediaRetained: false,
            cues: [SubtitleCue(start: 0, end: 1, text: "LATE", words: [])]
        )
    }

    private func temporaryURL(named name: String) -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("GSubsRaceTests", isDirectory: true)
            .appendingPathComponent("\(UUID().uuidString)-\(name)")
    }

    private func temporaryFile(named name: String) -> URL {
        let url = temporaryURL(named: name)
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        FileManager.default.createFile(atPath: url.path, contents: Data("test".utf8))
        return url
    }

    private func waitUntil(
        _ condition: @escaping () async -> Bool
    ) async throws {
        for _ in 0..<200 {
            if await condition() { return }
            try await Task.sleep(for: .milliseconds(5))
        }
        XCTFail("Timed out waiting for asynchronous state")
    }
}

private func isolatedDraftStore() -> ProjectDraftStore {
    let currentURL = FileManager.default.temporaryDirectory
        .appendingPathComponent("GSubsRaceDraft-\(UUID().uuidString)", isDirectory: true)
        .appendingPathComponent("Current", isDirectory: true)
    return ProjectDraftStore(
        currentURL: currentURL,
        appliesFileProtection: false,
        validatesPlayableMedia: false
    )
}

private struct StubAudioExtractor: AudioExtracting {
    let audioURL: URL

    func duration(of videoURL: URL) async throws -> Double { 1 }
    func extract(from videoURL: URL) async throws -> URL { audioURL }
}

private actor CountingAudioExtractor: AudioExtracting {
    let audioURL: URL
    private var extractions = 0

    init(audioURL: URL) {
        self.audioURL = audioURL
    }

    func duration(of videoURL: URL) async throws -> Double { 1 }

    func extract(from videoURL: URL) async throws -> URL {
        extractions += 1
        return audioURL
    }

    func extractionCount() -> Int { extractions }
}

private struct StubVideoPreviewPreparer: VideoPreviewPreparing {
    func prepareIfNeeded(from videoURL: URL) async throws -> URL? { nil }
}

private enum AccountDeletionBehavior: Sendable {
    case succeeds
    case confirmationUnavailable
    case rejected
    case controlled
}

private enum TranscriptionResponse: Sendable {
    case success(MobileTranscriptionResult)
    case apiError(status: Int, message: String)
    case networkError
}

private actor ControlledAPIClient: GSubsAPIClient {
    private var started = false
    private var continuation: CheckedContinuation<MobileTranscriptionResult, Error>?
    private let accountDeletionBehavior: AccountDeletionBehavior
    private var deletionRequests = 0
    private var deletionContinuation: CheckedContinuation<Void, Error>?
    private var transcriptionResponses: [TranscriptionResponse]
    private var transcriptionKeys: [String] = []
    private let pointsBalance: PointsBalance
    private var pointsRequests = 0

    init(
        accountDeletionBehavior: AccountDeletionBehavior = .succeeds,
        transcriptionResponses: [TranscriptionResponse] = [],
        pointsBalance: PointsBalance = PointsBalance(
            balance: 100,
            paidBalance: 100,
            promotionalBalance: 0,
            reversalDebt: 0,
            aiSpendableBalance: 100
        )
    ) {
        self.accountDeletionBehavior = accountDeletionBehavior
        self.transcriptionResponses = transcriptionResponses
        self.pointsBalance = pointsBalance
    }

    func login(email: String, password: String) async throws -> LoginResult {
        LoginResult(
            accessToken: "test-token",
            tokenType: "bearer",
            userId: "test-user",
            name: "Test",
            betaCreditsAwarded: 0
        )
    }

    func register(email: String, password: String, name: String) async throws {}

    func profile(token: String) async throws -> UserProfile {
        UserProfile(id: "test-user", email: "test@gsubs.local", name: "Test", provider: "local")
    }

    func points(token: String) async throws -> PointsBalance {
        pointsRequests += 1
        return pointsBalance
    }

    func pointsRequestCount() -> Int { pointsRequests }

    func logout(token: String) async {}

    func deleteAccount(token: String) async throws {
        deletionRequests += 1
        switch accountDeletionBehavior {
        case .succeeds:
            return
        case .confirmationUnavailable:
            throw AccountDeletionError.confirmationUnavailable
        case .rejected:
            throw APIError(status: 409, message: "Deletion is blocked")
        case .controlled:
            try await withCheckedThrowingContinuation {
                deletionContinuation = $0
            }
        }
    }

    func accountDeletionStarted() -> Bool { deletionRequests > 0 }

    func accountDeletionRequestCount() -> Int { deletionRequests }

    func completeAccountDeletion() {
        deletionContinuation?.resume(returning: ())
        deletionContinuation = nil
    }

    func transcribe(
        audioURL: URL,
        token: String,
        idempotencyKey: String
    ) async throws -> MobileTranscriptionResult {
        started = true
        transcriptionKeys.append(idempotencyKey)
        if !transcriptionResponses.isEmpty {
            switch transcriptionResponses.removeFirst() {
            case .success(let result):
                return result
            case .apiError(let status, let message):
                throw APIError(status: status, message: message)
            case .networkError:
                throw URLError(.networkConnectionLost)
            }
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func transcriptionStarted() -> Bool { started }

    func transcriptionRequestCount() -> Int { transcriptionKeys.count }

    func transcriptionKeysReceived() -> [String] { transcriptionKeys }

    func completeTranscription(with result: MobileTranscriptionResult) {
        continuation?.resume(returning: result)
        continuation = nil
    }
}

private actor ControlledVideoExporter: VideoExporting {
    private var started = false
    private var continuation: CheckedContinuation<URL, Error>?

    func export(
        videoURL: URL,
        cues: [SubtitleCue],
        style: SubtitleStyle
    ) async throws -> URL {
        started = true
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func exportStarted() -> Bool { started }

    func completeExport(with url: URL) {
        continuation?.resume(returning: url)
        continuation = nil
    }
}

private actor ControlledVideoPreviewPreparer: VideoPreviewPreparing {
    private var started = false
    private var continuation: CheckedContinuation<URL?, Error>?

    func prepareIfNeeded(from videoURL: URL) async throws -> URL? {
        started = true
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func preparationStarted() -> Bool { started }

    func completePreparation(with url: URL?) {
        continuation?.resume(returning: url)
        continuation = nil
    }
}
