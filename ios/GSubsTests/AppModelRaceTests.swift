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

    func testResetDeletesLateExportAndKeepsProjectIdle() async throws {
        let api = ControlledAPIClient()
        let exporter = ControlledVideoExporter()
        let model = AppModel(
            api: api,
            audioExtractor: StubAudioExtractor(audioURL: temporaryURL(named: "unused.m4a")),
            videoExporter: exporter,
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

    private var transcriptionResult: MobileTranscriptionResult {
        MobileTranscriptionResult(
            requestId: "late-result",
            durationSeconds: 1,
            creditsCharged: 30,
            balance: 70,
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

private struct StubAudioExtractor: AudioExtracting {
    let audioURL: URL

    func duration(of videoURL: URL) async throws -> Double { 1 }
    func extract(from videoURL: URL) async throws -> URL { audioURL }
}

private actor ControlledAPIClient: GSubsAPIClient {
    private var started = false
    private var continuation: CheckedContinuation<MobileTranscriptionResult, Error>?

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
        PointsBalance(
            balance: 100,
            paidBalance: 100,
            promotionalBalance: 0,
            reversalDebt: 0,
            aiSpendableBalance: 100
        )
    }

    func logout(token: String) async {}

    func transcribe(
        audioURL: URL,
        token: String,
        idempotencyKey: String
    ) async throws -> MobileTranscriptionResult {
        started = true
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func transcriptionStarted() -> Bool { started }

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
