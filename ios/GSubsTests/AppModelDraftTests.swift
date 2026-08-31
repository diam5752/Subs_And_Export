import Foundation
import XCTest

@testable import GSubs

@MainActor
final class AppModelDraftTests: XCTestCase {
    func testSameOwnerRestoresEditingDraftAndAutosavedStyle() async throws {
        let fixture = try DraftFixture()
        defer { fixture.cleanup() }
        let api = DraftAPI()
        let first = fixture.model(api: api)
        await first.restoreSession()
        await first.accept(PickedVideo(url: try fixture.makeScratchFile("first.mov")))
        let cue = SubtitleCue(start: 0, end: 1, text: "ΑΠΟΘΗΚΕΥΜΕΝΟ", words: [])
        first.cues = [cue]
        first.style.foreground = .cyan
        first.style.fontScale = 1.2
        await first.flushProjectDraft()

        let restored = fixture.model(api: DraftAPI())
        await restored.restoreSession()

        XCTAssertTrue(restored.isAuthenticated)
        XCTAssertEqual(restored.phase, .editing)
        XCTAssertEqual(restored.cues, [cue])
        XCTAssertEqual(restored.style.foreground, .cyan)
        XCTAssertEqual(restored.style.fontScale, 1.2)
        XCTAssertTrue(restored.videoURL?.path.hasPrefix(fixture.currentURL.path) == true)
        XCTAssertNil(restored.exportedURL)
        XCTAssertNil(restored.noticeMessage)
    }

    func testMidTranscriptionRestoresReadyWithSameIdempotencyKey() async throws {
        let fixture = try DraftFixture()
        defer { fixture.cleanup() }
        let firstAPI = DraftAPI(transcription: .suspend)
        let first = fixture.model(api: firstAPI)
        await first.restoreSession()
        await first.accept(PickedVideo(url: try fixture.makeScratchFile("source.mov")))
        let before = try await fixture.store.restore(ownerUserID: DraftAPI.user.id)

        first.generateSubtitles()
        try await waitUntil { await firstAPI.transcriptionKeys().count == 1 }

        let retryAPI = DraftAPI(
            transcription: .failure(
                status: 409,
                message: "Transcription is already in progress"
            )
        )
        let relaunched = fixture.model(api: retryAPI)
        await relaunched.restoreSession()
        XCTAssertEqual(relaunched.phase, .ready)
        XCTAssertTrue(relaunched.cues.isEmpty)
        relaunched.generateSubtitles()
        try await waitUntil { await retryAPI.transcriptionKeys().count == 1 }

        let retryKeys = await retryAPI.transcriptionKeys()
        XCTAssertEqual(retryKeys.first, before?.draft.transcriptionKey)
        first.resetProject()
        relaunched.resetProject()
    }

    func testTransportAndServerFailureKeepLockedDraftAndTokenForRetry() async throws {
        for failure in [SessionFailure.transport, .server] {
            let fixture = try DraftFixture()
            defer { fixture.cleanup() }
            _ = try await fixture.seedDraft()
            let api = DraftAPI(sessionResponses: [failure.response, .success])
            let model = fixture.model(api: api)

            await model.restoreSession()
            XCTAssertFalse(model.isAuthenticated)
            XCTAssertNil(model.videoURL)
            let lockedDraft = try await fixture.store.restore(ownerUserID: DraftAPI.user.id)
            XCTAssertNotNil(lockedDraft)

            await model.restoreSession()
            XCTAssertTrue(model.isAuthenticated)
            XCTAssertEqual(model.phase, .ready)
            XCTAssertNotNil(model.videoURL)
        }
    }

    func testUnauthorizedAndForbiddenClearDraftAndToken() async throws {
        for status in [401, 403] {
            let fixture = try DraftFixture()
            defer { fixture.cleanup() }
            _ = try await fixture.seedDraft()
            let api = DraftAPI(sessionResponses: [.apiError(status)])
            let model = fixture.model(api: api)

            await model.restoreSession()
            await model.restoreSession()

            XCTAssertFalse(model.isAuthenticated)
            XCTAssertNil(model.videoURL)
            let clearedDraft = try await fixture.store.restore(ownerUserID: DraftAPI.user.id)
            let profileRequestCount = await api.profileRequestCount()
            XCTAssertNil(clearedDraft)
            XCTAssertEqual(profileRequestCount, 1)
        }
    }

    func testOwnerMismatchIsPurgedWithoutExposingProject() async throws {
        let fixture = try DraftFixture()
        defer { fixture.cleanup() }
        _ = try await fixture.seedDraft(ownerUserID: "another-owner")
        let model = fixture.model(api: DraftAPI())

        await model.restoreSession()

        XCTAssertTrue(model.isAuthenticated)
        XCTAssertEqual(model.phase, .idle)
        XCTAssertNil(model.videoURL)
        XCTAssertTrue(model.cues.isEmpty)
        let removedDraft = try await fixture.store.restore(ownerUserID: "another-owner")
        XCTAssertNil(removedDraft)
    }

    func testResetAndSignOutPurgePersistentDraft() async throws {
        let fixture = try DraftFixture()
        defer { fixture.cleanup() }
        let model = fixture.model(api: DraftAPI())
        await model.restoreSession()
        await model.accept(PickedVideo(url: try fixture.makeScratchFile("reset.mov")))

        model.resetProject()
        try await waitUntil {
            (try? await fixture.store.restore(ownerUserID: DraftAPI.user.id)) == nil
        }
        XCTAssertEqual(model.phase, .idle)

        await model.accept(PickedVideo(url: try fixture.makeScratchFile("signout.mov")))
        await model.signOut()
        XCTAssertFalse(model.isAuthenticated)
        let signedOutDraft = try await fixture.store.restore(ownerUserID: DraftAPI.user.id)
        XCTAssertNil(signedOutDraft)
    }

    func testConfirmedAndAmbiguousDeletionPurgeButRejectionRetains() async throws {
        for deletion in [DeletionResult.confirmed, .ambiguous] {
            let fixture = try DraftFixture()
            defer { fixture.cleanup() }
            let model = fixture.model(api: DraftAPI(deletion: deletion))
            await model.restoreSession()
            await model.accept(PickedVideo(url: try fixture.makeScratchFile("delete.mov")))

            await model.deleteAccount()

            XCTAssertFalse(model.isAuthenticated)
            let removedDraft = try await fixture.store.restore(ownerUserID: DraftAPI.user.id)
            XCTAssertNil(removedDraft)
        }

        let retainedFixture = try DraftFixture()
        defer { retainedFixture.cleanup() }
        let retained = retainedFixture.model(api: DraftAPI(deletion: .rejected))
        await retained.restoreSession()
        await retained.accept(PickedVideo(url: try retainedFixture.makeScratchFile("retain.mov")))
        await retained.deleteAccount()

        XCTAssertTrue(retained.isAuthenticated)
        XCTAssertEqual(retained.phase, .ready)
        let retainedDraft = try await retainedFixture.store.restore(
            ownerUserID: DraftAPI.user.id
        )
        XCTAssertNotNil(retainedDraft)
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

private final class DraftFixture: @unchecked Sendable {
    let rootURL: URL
    let currentURL: URL
    let scratchURL: URL
    let store: ProjectDraftStore

    init() throws {
        rootURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("AppModelDraftTests-\(UUID().uuidString)")
        currentURL = rootURL.appendingPathComponent("Current", isDirectory: true)
        scratchURL = rootURL.appendingPathComponent("Scratch", isDirectory: true)
        try FileManager.default.createDirectory(
            at: scratchURL,
            withIntermediateDirectories: true
        )
        store = ProjectDraftStore(
            currentURL: currentURL,
            appliesFileProtection: false,
            validatesPlayableMedia: false
        )
    }

    @MainActor
    func model(api: DraftAPI) -> AppModel {
        AppModel(
            api: api,
            audioExtractor: DraftAudioExtractor(directory: scratchURL),
            previewPreparer: DraftPreviewPreparer(),
            draftStore: store,
            initialToken: "test-token"
        )
    }

    func makeScratchFile(_ name: String) throws -> URL {
        let url = scratchURL.appendingPathComponent("\(UUID().uuidString)-\(name)")
        try Data("media".utf8).write(to: url)
        return url
    }

    func seedDraft(ownerUserID: String = DraftAPI.user.id) async throws
        -> RestoredProjectDraft
    {
        try await store.commitProject(
            ownerUserID: ownerUserID,
            sourceURL: makeScratchFile("seed.mov"),
            previewURL: nil,
            duration: 1,
            transcriptionKey: UUID().uuidString,
            revision: 1
        )
    }

    func cleanup() {
        try? FileManager.default.removeItem(at: rootURL)
    }
}

private enum SessionResponse: Sendable {
    case success
    case transport
    case apiError(Int)
}

private enum SessionFailure: Sendable {
    case transport
    case server

    var response: SessionResponse {
        switch self {
        case .transport: .transport
        case .server: .apiError(500)
        }
    }
}

private enum TranscriptionBehavior: Sendable {
    case success
    case suspend
    case failure(status: Int, message: String)
}

private enum DeletionResult: Sendable {
    case confirmed
    case ambiguous
    case rejected
}

private actor DraftAPI: GSubsAPIClient {
    static let user = UserProfile(
        id: "draft-owner",
        email: "draft@gsubs.local",
        name: "Draft Owner",
        provider: "local"
    )

    private var sessionResponses: [SessionResponse]
    private let transcription: TranscriptionBehavior
    private let deletion: DeletionResult
    private var profileRequests = 0
    private var keys: [String] = []

    init(
        sessionResponses: [SessionResponse] = [.success],
        transcription: TranscriptionBehavior = .success,
        deletion: DeletionResult = .confirmed
    ) {
        self.sessionResponses = sessionResponses
        self.transcription = transcription
        self.deletion = deletion
    }

    func login(email: String, password: String) async throws -> LoginResult {
        LoginResult(
            accessToken: "test-token",
            tokenType: "bearer",
            userId: Self.user.id,
            name: Self.user.name,
            betaCreditsAwarded: 0
        )
    }

    func register(email: String, password: String, name: String) async throws {}

    func profile(token: String) async throws -> UserProfile {
        profileRequests += 1
        let response = sessionResponses.isEmpty ? .success : sessionResponses.removeFirst()
        switch response {
        case .success:
            return Self.user
        case .transport:
            throw URLError(.networkConnectionLost)
        case .apiError(let status):
            throw APIError(status: status, message: "session failed")
        }
    }

    func profileRequestCount() -> Int { profileRequests }

    func points(token: String) async throws -> PointsBalance {
        PointsBalance(
            balance: 100,
            paidBalance: 100,
            promotionalBalance: 0,
            reversalDebt: 0,
            aiSpendableBalance: 100
        )
    }

    func logout(token: String) async {}

    func deleteAccount(token: String) async throws {
        switch deletion {
        case .confirmed:
            return
        case .ambiguous:
            throw AccountDeletionError.confirmationUnavailable
        case .rejected:
            throw APIError(status: 409, message: "Deletion is blocked")
        }
    }

    func transcribe(
        audioURL: URL,
        token: String,
        idempotencyKey: String
    ) async throws -> MobileTranscriptionResult {
        keys.append(idempotencyKey)
        switch transcription {
        case .success:
            return MobileTranscriptionResult(
                requestId: "draft-test",
                durationSeconds: 1,
                creditsCharged: 30,
                balance: 70,
                videoUploaded: false,
                serverMediaRetained: false,
                cues: [SubtitleCue(start: 0, end: 1, text: "TEST", words: [])]
            )
        case .suspend:
            try await Task.sleep(for: .seconds(60))
            throw CancellationError()
        case .failure(let status, let message):
            throw APIError(status: status, message: message)
        }
    }

    func transcriptionKeys() -> [String] { keys }
}

private struct DraftAudioExtractor: AudioExtracting {
    let directory: URL

    func duration(of videoURL: URL) async throws -> Double { 1 }

    func extract(from videoURL: URL) async throws -> URL {
        let url = directory.appendingPathComponent("audio-\(UUID().uuidString).m4a")
        try Data("audio".utf8).write(to: url)
        return url
    }
}

private struct DraftPreviewPreparer: VideoPreviewPreparing {
    func prepareIfNeeded(from videoURL: URL) async throws -> URL? { nil }
}
