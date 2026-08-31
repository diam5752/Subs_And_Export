import Foundation
import XCTest

@testable import GSubs

final class ProjectDraftStoreTests: XCTestCase {
    func testRoundTripPersistsRelativeManifestAndEditingState() async throws {
        let fixture = try makeFixture(withPreview: true)
        defer { fixture.cleanup() }

        let committed = try await fixture.store.commitProject(
            ownerUserID: "owner-1",
            sourceURL: fixture.sourceURL,
            previewURL: fixture.previewURL,
            duration: 12,
            transcriptionKey: UUID().uuidString,
            revision: 1
        )
        let cue = SubtitleCue(start: 0, end: 1, text: "ΔΟΚΙΜΗ", words: [])
        var style = SubtitleStyle()
        style.foreground = .cyan
        style.fontScale = 1.2
        let edited = committed.draft.updating(
            revision: 2,
            cues: [cue],
            style: style,
            transcriptionKey: committed.draft.transcriptionKey,
            phase: .editing
        )
        try await fixture.store.save(edited)

        let restoredValue = try await fixture.store.restore(ownerUserID: "owner-1")
        let restored = try XCTUnwrap(restoredValue)
        XCTAssertEqual(restored.draft, edited)
        XCTAssertEqual(restored.sourceURL, committed.sourceURL)
        XCTAssertEqual(restored.previewURL, committed.previewURL)
        XCTAssertTrue(restored.sourceURL.path.hasPrefix(fixture.currentURL.path))
        XCTAssertFalse(edited.sourceRelativePath.hasPrefix("/"))
        XCTAssertFalse(edited.previewRelativePath?.hasPrefix("/") ?? true)

        let manifest = try Data(contentsOf: fixture.manifestURL)
        XCTAssertLessThan(manifest.count, ProjectDraftValidator.maximumManifestBytes)
        XCTAssertEqual(try JSONDecoder().decode(ProjectDraft.self, from: manifest), edited)
    }

    func testMissingPreviewFallsBackToPersistentSource() async throws {
        let fixture = try makeFixture(withPreview: true)
        defer { fixture.cleanup() }
        let committed = try await commit(fixture: fixture)
        try FileManager.default.removeItem(at: committed.previewURL)

        let restoredValue = try await fixture.store.restore(ownerUserID: "owner-1")
        let restored = try XCTUnwrap(restoredValue)

        XCTAssertEqual(restored.previewURL, restored.sourceURL)
        XCTAssertEqual(restored.draft.previewRelativePath, committed.draft.previewRelativePath)
    }

    func testOwnerMismatchAndCorruptManifestAreNeverRestored() async throws {
        let fixture = try makeFixture()
        defer { fixture.cleanup() }
        _ = try await commit(fixture: fixture)

        await assertDraftError(.ownerMismatch) {
            _ = try await fixture.store.restore(ownerUserID: "owner-2")
        }

        try Data("not-json".utf8).write(to: fixture.manifestURL, options: .atomic)
        await assertDraftError(.corrupt) {
            _ = try await fixture.store.restore(ownerUserID: "owner-1")
        }
    }

    func testUnknownSchemaAndPathTraversalAreRejected() async throws {
        let fixture = try makeFixture()
        defer { fixture.cleanup() }
        let committed = try await commit(fixture: fixture)
        let unknownSchema = copy(
            committed.draft,
            schemaVersion: 99,
            revision: 2
        )
        try write(unknownSchema, to: fixture.manifestURL)

        await assertDraftError(.corrupt) {
            _ = try await fixture.store.restore(ownerUserID: "owner-1")
        }

        let traversal = copy(
            committed.draft,
            revision: 3,
            sourceRelativePath: "../outside.mp4"
        )
        try write(traversal, to: fixture.manifestURL)
        await assertDraftError(.corrupt) {
            _ = try await fixture.store.restore(ownerUserID: "owner-1")
        }
    }

    func testSymbolicLinkSourceIsRejected() async throws {
        let fixture = try makeFixture()
        defer { fixture.cleanup() }
        let committed = try await commit(fixture: fixture)
        let external = fixture.rootURL.appendingPathComponent("external.mp4")
        try Data("external".utf8).write(to: external)
        try FileManager.default.removeItem(at: committed.sourceURL)
        try FileManager.default.createSymbolicLink(
            at: committed.sourceURL,
            withDestinationURL: external
        )

        await assertDraftError(.corrupt) {
            _ = try await fixture.store.restore(ownerUserID: "owner-1")
        }
    }

    func testNewerRevisionWinsAndOlderSaveIsRejected() async throws {
        let fixture = try makeFixture()
        defer { fixture.cleanup() }
        let committed = try await commit(fixture: fixture)
        let newerCue = SubtitleCue(start: 0, end: 1, text: "NEW", words: [])
        let newer = committed.draft.updating(
            revision: 3,
            cues: [newerCue],
            style: SubtitleStyle(),
            transcriptionKey: committed.draft.transcriptionKey,
            phase: .editing
        )
        let older = committed.draft.updating(
            revision: 2,
            cues: [SubtitleCue(start: 0, end: 1, text: "OLD", words: [])],
            style: SubtitleStyle(),
            transcriptionKey: committed.draft.transcriptionKey,
            phase: .editing
        )

        try await fixture.store.save(newer)
        await assertDraftError(.staleRevision) {
            try await fixture.store.save(older)
        }
        let restored = try await fixture.store.restore(ownerUserID: "owner-1")
        XCTAssertEqual(restored?.draft.cues, [newerCue])
        XCTAssertEqual(restored?.draft.revision, 3)
    }

    func testPurgePreventsDelayedSaveFromResurrectingProject() async throws {
        let fixture = try makeFixture()
        defer { fixture.cleanup() }
        let committed = try await commit(fixture: fixture)

        try await fixture.store.purge(ifNewerThan: 2)
        let delayed = committed.draft.updating(
            revision: 3,
            cues: [],
            style: SubtitleStyle(),
            transcriptionKey: committed.draft.transcriptionKey,
            phase: .ready
        )
        await assertDraftError(.staleRevision) {
            try await fixture.store.save(delayed)
        }

        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.manifestURL.path))
        let restored = try await fixture.store.restore(ownerUserID: "owner-1")
        XCTAssertNil(restored)
    }

    func testForcePurgeTombstoneRejectsLateCommitAndAllowsNewerProject() async throws {
        let fixture = try makeFixture()
        defer { fixture.cleanup() }
        _ = try await commit(fixture: fixture)

        let tombstoneRevision = try await fixture.store.purgeAll()
        await assertDraftError(.staleRevision) {
            _ = try await fixture.store.commitProject(
                ownerUserID: "owner-1",
                sourceURL: fixture.sourceURL,
                previewURL: nil,
                duration: 12,
                transcriptionKey: UUID().uuidString,
                revision: tombstoneRevision
            )
        }
        let replacement = try await fixture.store.commitProject(
            ownerUserID: "owner-1",
            sourceURL: fixture.sourceURL,
            previewURL: nil,
            duration: 12,
            transcriptionKey: UUID().uuidString,
            revision: tombstoneRevision + 1
        )

        XCTAssertEqual(replacement.draft.revision, tombstoneRevision + 1)
    }

    func testInvalidVideoNeverPublishesStagingProject() async throws {
        let fixture = try makeFixture()
        defer { fixture.cleanup() }
        let validatingStore = ProjectDraftStore(
            currentURL: fixture.currentURL,
            appliesFileProtection: false
        )

        await assertDraftError(.corrupt) {
            _ = try await validatingStore.commitProject(
                ownerUserID: "owner-1",
                sourceURL: fixture.sourceURL,
                previewURL: nil,
                duration: 12,
                transcriptionKey: UUID().uuidString,
                revision: 1
            )
        }

        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.currentURL.path))
        let siblings = try FileManager.default.contentsOfDirectory(
            at: fixture.currentURL.deletingLastPathComponent(),
            includingPropertiesForKeys: nil
        )
        XCTAssertFalse(siblings.contains { $0.lastPathComponent.hasPrefix("Staging-") })
    }

    private func commit(fixture: Fixture) async throws -> RestoredProjectDraft {
        try await fixture.store.commitProject(
            ownerUserID: "owner-1",
            sourceURL: fixture.sourceURL,
            previewURL: fixture.previewURL,
            duration: 12,
            transcriptionKey: UUID().uuidString,
            revision: 1
        )
    }

    private func makeFixture(withPreview: Bool = false) throws -> Fixture {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ProjectDraftStoreTests-\(UUID().uuidString)")
        let current = root.appendingPathComponent("Current", isDirectory: true)
        let scratch = root.appendingPathComponent("Scratch", isDirectory: true)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        let source = scratch.appendingPathComponent("source.mov")
        try Data("source-media".utf8).write(to: source)
        let preview = scratch.appendingPathComponent("preview.mp4")
        if withPreview { try Data("preview-media".utf8).write(to: preview) }
        return Fixture(
            rootURL: root,
            currentURL: current,
            sourceURL: source,
            previewURL: withPreview ? preview : nil,
            store: ProjectDraftStore(
                currentURL: current,
                appliesFileProtection: false,
                validatesPlayableMedia: false
            )
        )
    }

    private func copy(
        _ draft: ProjectDraft,
        schemaVersion: Int = ProjectDraft.currentSchemaVersion,
        revision: UInt64,
        sourceRelativePath: String? = nil
    ) -> ProjectDraft {
        ProjectDraft(
            schemaVersion: schemaVersion,
            projectID: draft.projectID,
            revision: revision,
            ownerUserID: draft.ownerUserID,
            sourceRelativePath: sourceRelativePath ?? draft.sourceRelativePath,
            previewRelativePath: draft.previewRelativePath,
            duration: draft.duration,
            cues: draft.cues,
            style: draft.style,
            transcriptionKey: draft.transcriptionKey,
            phase: draft.phase
        )
    }

    private func write(_ draft: ProjectDraft, to url: URL) throws {
        try JSONEncoder().encode(draft).write(to: url, options: .atomic)
    }

    private func assertDraftError(
        _ expected: ProjectDraftError,
        operation: () async throws -> Void
    ) async {
        do {
            try await operation()
            XCTFail("Expected \(expected)")
        } catch let error as ProjectDraftError {
            XCTAssertEqual(error, expected)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }
}

private struct Fixture: @unchecked Sendable {
    let rootURL: URL
    let currentURL: URL
    let sourceURL: URL
    let previewURL: URL?
    let store: ProjectDraftStore

    var manifestURL: URL {
        currentURL.appendingPathComponent("manifest.json")
    }

    func cleanup() {
        try? FileManager.default.removeItem(at: rootURL)
    }
}
