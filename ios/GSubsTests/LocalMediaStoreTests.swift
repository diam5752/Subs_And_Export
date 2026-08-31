import Foundation
import XCTest

@testable import GSubs

final class LocalMediaStoreTests: XCTestCase {
    func testLaunchCleanupQuarantinesOldMediaWithoutTouchingNewMedia() throws {
        let parent = FileManager.default.temporaryDirectory
            .appendingPathComponent("GSubsStoreTests-\(UUID().uuidString)", isDirectory: true)
        let root = parent.appendingPathComponent("GSubs", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("old".utf8).write(to: root.appendingPathComponent("old.mp4"))
        defer { try? FileManager.default.removeItem(at: parent) }

        let staleURLs = LocalMediaStore.quarantineStaleMedia(at: root)

        XCTAssertEqual(staleURLs.count, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: staleURLs[0].appendingPathComponent("old.mp4").path
            ))

        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let newMedia = root.appendingPathComponent("new.mp4")
        try Data("new".utf8).write(to: newMedia)
        for staleURL in staleURLs {
            try? FileManager.default.removeItem(at: staleURL)
        }

        XCTAssertEqual(try Data(contentsOf: newMedia), Data("new".utf8))
    }

    func testLaunchCleanupFindsEarlierQuarantineDirectories() throws {
        let parent = FileManager.default.temporaryDirectory
            .appendingPathComponent("GSubsStoreTests-\(UUID().uuidString)", isDirectory: true)
        let root = parent.appendingPathComponent("GSubs", isDirectory: true)
        let prior = parent.appendingPathComponent("GSubs-Stale-prior", isDirectory: true)
        try FileManager.default.createDirectory(at: prior, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: parent) }

        let staleURLs = LocalMediaStore.quarantineStaleMedia(at: root)

        XCTAssertEqual(staleURLs, [prior])
    }
}
