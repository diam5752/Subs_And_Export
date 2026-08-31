import AVFoundation
import Foundation

protocol VideoPreviewPreparing: Sendable {
    func prepareIfNeeded(from videoURL: URL) async throws -> URL?
}

struct VideoPreviewPreparer {
    static let maximumPreviewDimension = 1_920.0

    func prepareIfNeeded(from videoURL: URL) async throws -> URL? {
        try Task.checkCancellation()
        let asset = AVURLAsset(url: videoURL)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw LocalMediaError.missingVideo
        }
        async let naturalSize = track.load(.naturalSize)
        async let transform = track.load(.preferredTransform)
        let displaySize = CGRect(origin: .zero, size: try await naturalSize)
            .applying(try await transform)
            .standardized.size

        guard Self.requiresProxy(displaySize: displaySize) else { return nil }
        try Task.checkCancellation()
        let isCompatible = await AVAssetExportSession.compatibility(
            ofExportPreset: AVAssetExportPreset1280x720,
            with: asset,
            outputFileType: .mp4
        )
        try Task.checkCancellation()
        guard isCompatible,
            let exporter = AVAssetExportSession(
                asset: asset,
                presetName: AVAssetExportPreset1280x720
            )
        else {
            return nil
        }
        let destination = try proxyURL()
        exporter.outputURL = destination
        exporter.outputFileType = .mp4
        exporter.shouldOptimizeForNetworkUse = true
        await exporter.run()

        if Task.isCancelled {
            try? FileManager.default.removeItem(at: destination)
            throw CancellationError()
        }
        guard exporter.status == .completed else {
            try? FileManager.default.removeItem(at: destination)
            return nil
        }
        return try await Self.validatedProxy(at: destination)
    }

    static func validatedProxy(at destination: URL) async throws -> URL? {
        var retainsProxy = false
        defer {
            if !retainsProxy {
                try? FileManager.default.removeItem(at: destination)
            }
        }

        try Task.checkCancellation()
        let proxy = AVURLAsset(url: destination)
        let proxyTracks = try await proxy.loadTracks(withMediaType: .video)
        let proxyDuration = try await proxy.load(.duration).seconds
        try Task.checkCancellation()
        guard !proxyTracks.isEmpty, proxyDuration.isFinite, proxyDuration > 0 else {
            return nil
        }
        retainsProxy = true
        return destination
    }

    static func requiresProxy(displaySize: CGSize) -> Bool {
        max(abs(displaySize.width), abs(displaySize.height)) > maximumPreviewDimension
    }

    private func proxyURL() throws -> URL {
        try LocalMediaStore.temporaryDirectory(named: "PreviewStaging")
            .appendingPathComponent("Preview-\(UUID().uuidString).mp4")
    }
}

extension VideoPreviewPreparer: VideoPreviewPreparing {}
