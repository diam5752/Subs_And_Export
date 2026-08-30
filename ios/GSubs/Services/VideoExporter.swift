import AVFoundation
import CoreImage
import Foundation
import UIKit

protocol VideoExporting: Sendable {
    func export(
        videoURL: URL,
        cues: [SubtitleCue],
        style: SubtitleStyle
    ) async throws -> URL
}

struct VideoExporter {
    func export(
        videoURL: URL,
        cues: [SubtitleCue],
        style: SubtitleStyle
    ) async throws -> URL {
        try Task.checkCancellation()
        let sourceAsset = AVURLAsset(url: videoURL)
        let duration = try await sourceAsset.load(.duration)
        try Task.checkCancellation()
        guard duration.seconds.isFinite, duration.seconds > 0 else {
            throw LocalMediaError.invalidDuration
        }
        guard !(try await sourceAsset.loadTracks(withMediaType: .video)).isEmpty else {
            throw LocalMediaError.missingVideo
        }
        try Task.checkCancellation()
        let renderer = SubtitleFrameRenderer(cues: cues, style: style)
        let videoComposition = AVVideoComposition(asset: sourceAsset, applyingCIFiltersWithHandler: { request in
            let source = request.sourceImage
            let time = request.compositionTime.seconds
            let caption = renderer.caption(
                at: time,
                frameExtent: source.extent
            )
            guard let caption else {
                request.finish(with: source, context: nil)
                return
            }
            request.finish(
                with: caption.composited(over: source).cropped(to: source.extent),
                context: nil
            )
        })
        return try await exportAndVerify(
            sourceAsset: sourceAsset,
            videoComposition: videoComposition
        )
    }

    private func exportAndVerify(
        sourceAsset: AVAsset,
        videoComposition: AVVideoComposition
    ) async throws -> URL {
        guard let exporter = AVAssetExportSession(
            asset: sourceAsset,
            presetName: AVAssetExportPresetHighestQuality
        ) else { throw LocalMediaError.cannotExport }
        let destination = exportURL()
        try? FileManager.default.removeItem(at: destination)
        exporter.outputURL = destination
        exporter.outputFileType = .mp4
        exporter.videoComposition = videoComposition
        exporter.shouldOptimizeForNetworkUse = true
        await exporter.run()
        if Task.isCancelled {
            try? FileManager.default.removeItem(at: destination)
            throw CancellationError()
        }
        guard exporter.status == .completed else {
            try? FileManager.default.removeItem(at: destination)
            throw exporter.error ?? LocalMediaError.cannotExport
        }
        let verification = AVURLAsset(url: destination)
        let tracks = try await verification.loadTracks(withMediaType: .video)
        let duration = try await verification.load(.duration).seconds
        guard !tracks.isEmpty, duration.isFinite, duration > 0 else {
            try? FileManager.default.removeItem(at: destination)
            throw LocalMediaError.cannotDecodeExport
        }
        return destination
    }

    private func exportURL() -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("GSubs/Exports", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent("GSubs-\(UUID().uuidString).mp4")
    }
}

extension VideoExporter: VideoExporting {}

final class SubtitleFrameRenderer: @unchecked Sendable {
    private let cues: [SubtitleCue]
    private let style: SubtitleStyle
    private let cache = NSCache<NSString, CaptionImage>()

    init(cues: [SubtitleCue], style: SubtitleStyle) {
        self.cues = cues.sorted { $0.start < $1.start }
        self.style = style
        cache.totalCostLimit = 24 * 1_024 * 1_024
    }

    func caption(at time: Double, frameExtent: CGRect) -> CIImage? {
        guard let cue = activeCue(at: time),
              !cue.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              frameExtent.width > 0,
              frameExtent.height > 0 else { return nil }
        let key = NSString(
            string: "\(cue.id)|\(cue.text)|\(Int(frameExtent.width.rounded()))|\(style.foreground.rawValue)|\(style.fontScale)"
        )
        let image: CIImage
        if let cached = cache.object(forKey: key) {
            image = cached.image
        } else {
            guard let rendered = makeCaption(text: cue.text, frameWidth: frameExtent.width) else {
                return nil
            }
            image = rendered
            let cost = Int(rendered.extent.width * rendered.extent.height * 4)
            cache.setObject(CaptionImage(rendered), forKey: key, cost: cost)
        }
        let maxWidth = frameExtent.width * 0.88
        let scale = min(1, maxWidth / max(image.extent.width, 1))
        let normalized = image.transformed(by: CGAffineTransform(
            translationX: -image.extent.minX,
            y: -image.extent.minY
        ))
        let scaled = normalized.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        return scaled.transformed(by: CGAffineTransform(
            translationX: frameExtent.midX - scaled.extent.width / 2,
            y: frameExtent.minY + frameExtent.height * style.bottomOffset
        ))
    }

    private func activeCue(at time: Double) -> SubtitleCue? {
        var lower = 0
        var upper = cues.count
        while lower < upper {
            let middle = (lower + upper) / 2
            if cues[middle].start <= time {
                lower = middle + 1
            } else {
                upper = middle
            }
        }
        guard lower > 0 else { return nil }
        let candidate = cues[lower - 1]
        return candidate.contains(time) ? candidate : nil
    }

    private func makeCaption(text: String, frameWidth: CGFloat) -> CIImage? {
        let attributed = NSAttributedString(
            string: text.uppercased(),
            attributes: [
                .font: UIFont.systemFont(
                    ofSize: max(18, frameWidth * 0.058 * style.fontScale),
                    weight: .black
                ),
                .foregroundColor: style.foreground.uiColor,
                .strokeColor: UIColor.black,
                .strokeWidth: -4.0
            ]
        )
        guard let filter = CIFilter(name: "CIAttributedTextImageGenerator") else { return nil }
        filter.setValue(attributed, forKey: "inputText")
        filter.setValue(1.0, forKey: "inputScaleFactor")
        return filter.outputImage
    }
}

private final class CaptionImage: NSObject {
    let image: CIImage

    init(_ image: CIImage) {
        self.image = image
    }
}

private extension SubtitleColor {
    var uiColor: UIColor {
        switch self {
        case .yellow: .systemYellow
        case .white: .white
        case .cyan: .cyan
        }
    }
}
