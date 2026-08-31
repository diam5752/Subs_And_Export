import CoreGraphics
import XCTest

@testable import GSubs

final class VideoPreviewPreparerTests: XCTestCase {
    func testOnlyMediaAboveFullHDNeedsAProxy() {
        XCTAssertFalse(
            VideoPreviewPreparer.requiresProxy(
                displaySize: CGSize(width: 1_080, height: 1_920)
            ))
        XCTAssertFalse(
            VideoPreviewPreparer.requiresProxy(
                displaySize: CGSize(width: 1_920, height: 1_080)
            ))
        XCTAssertTrue(
            VideoPreviewPreparer.requiresProxy(
                displaySize: CGSize(width: 2_160, height: 3_840)
            ))
    }

    func testValidationFailureDeletesTheCreatedProxy() async throws {
        let proxyURL = temporaryProxyURL()
        try Data("not-a-video".utf8).write(to: proxyURL)
        var validationFailed = false

        do {
            _ = try await VideoPreviewPreparer.validatedProxy(at: proxyURL)
        } catch {
            validationFailed = true
        }

        XCTAssertTrue(validationFailed, "The fixture must exercise a throwing AVAsset load")
        XCTAssertFalse(FileManager.default.fileExists(atPath: proxyURL.path))
    }

    func testCancellationDuringValidationDeletesTheCreatedProxy() async throws {
        let proxyURL = temporaryProxyURL()
        try Data("pending-proxy".utf8).write(to: proxyURL)
        let validation = Task {
            try await VideoPreviewPreparer.validatedProxy(at: proxyURL)
        }
        validation.cancel()

        do {
            _ = try await validation.value
            XCTFail("Expected validation cancellation")
        } catch is CancellationError {
            // Expected.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: proxyURL.path))
    }

    private func temporaryProxyURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("Proxy-\(UUID().uuidString)")
            .appendingPathExtension("mp4")
    }
}
