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
        let videoComposition = AVVideoComposition(
            asset: sourceAsset,
            applyingCIFiltersWithHandler: { request in
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
        let is1080pCompatible = await AVAssetExportSession.compatibility(
            ofExportPreset: AVAssetExportPreset1920x1080,
            with: sourceAsset,
            outputFileType: .mp4
        )
        let preset =
            is1080pCompatible
            ? AVAssetExportPreset1920x1080
            : AVAssetExportPresetHighestQuality
        guard
            let exporter = AVAssetExportSession(
                asset: sourceAsset,
                presetName: preset
            )
        else { throw LocalMediaError.cannotExport }
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
        return try await Self.validatedExport(at: destination)
    }

    static func validatedExport(at destination: URL) async throws -> URL {
        var retainsExport = false
        defer {
            if !retainsExport {
                try? FileManager.default.removeItem(at: destination)
            }
        }

        try Task.checkCancellation()
        let verification = AVURLAsset(url: destination)
        let tracks = try await verification.loadTracks(withMediaType: .video)
        let duration = try await verification.load(.duration).seconds
        try Task.checkCancellation()
        guard !tracks.isEmpty, duration.isFinite, duration > 0 else {
            throw LocalMediaError.cannotDecodeExport
        }
        retainsExport = true
        return destination
    }

    private func exportURL() -> URL {
        let directory =
            (try? LocalMediaStore.temporaryDirectory(named: "Exports"))
            ?? FileManager.default.temporaryDirectory
        return directory.appendingPathComponent("GSubs-\(UUID().uuidString).mp4")
    }
}

extension VideoExporter: VideoExporting {}

final class SubtitleFrameRenderer: @unchecked Sendable {
    private let timeline: SubtitleTimeline
    private let style: SubtitleStyle
    private let cache = NSCache<NSString, CaptionImage>()

    init(cues: [SubtitleCue], style: SubtitleStyle) {
        timeline = SubtitleTimeline(cues: cues)
        self.style = style
        cache.totalCostLimit = 24 * 1_024 * 1_024
    }

    func caption(at time: Double, frameExtent: CGRect) -> CIImage? {
        guard let cue = activeCue(at: time),
            !cue.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            frameExtent.width > 0,
            frameExtent.height > 0
        else { return nil }
        let key = NSString(
            string:
                "\(cue.id)|\(cue.text)|\(Int(frameExtent.width.rounded()))|\(style.foreground.rawValue)|\(style.fontScale)"
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
        let maxWidth = SubtitleLayout.maximumCaptionWidth(frameWidth: frameExtent.width)
        let scale = min(1, maxWidth / max(image.extent.width, 1))
        let normalized = image.transformed(
            by: CGAffineTransform(
                translationX: -image.extent.minX,
                y: -image.extent.minY
            ))
        let scaled = normalized.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let bottomEdge = SubtitlePlacement.bottomEdgeFromBottom(
            frameHeight: frameExtent.height,
            captionHeight: scaled.extent.height,
            bottomOffset: style.resolvedBottomOffset(for: cue)
        )
        return scaled.transformed(
            by: CGAffineTransform(
                translationX: frameExtent.midX - scaled.extent.width / 2,
                y: frameExtent.minY + bottomEdge
            ))
    }

    private func activeCue(at time: Double) -> SubtitleCue? {
        timeline.activeCue(at: time)
    }

    private func makeCaption(text: String, frameWidth: CGFloat) -> CIImage? {
        let normalizedText = SubtitleLayout.normalizedText(text)
        guard !normalizedText.isEmpty else { return nil }

        let maximumTextWidth = SubtitleLayout.maximumTextWidth(frameWidth: frameWidth)
        let fontSize = SubtitleLayout.resolvedFontSize(
            text: normalizedText,
            frameWidth: frameWidth,
            scale: style.fontScale
        )
        let layout = captionLayout(
            text: normalizedText,
            fontSize: fontSize,
            maximumWidth: maximumTextWidth
        )

        let padding = SubtitleLayout.verticalPadding(frameWidth: frameWidth)
        let canvasSize = CGSize(
            width: ceil(min(maximumTextWidth, layout.bounds.width)) + padding * 2,
            height: ceil(
                min(
                    layout.bounds.height,
                    layout.font.lineHeight * SubtitleLayout.maximumLineHeightMultiplier
                )) + padding * 2
        )
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = false
        let renderer = UIGraphicsImageRenderer(size: canvasSize, format: format)
        let bitmap = renderer.image { _ in
            layout.text.draw(
                with: CGRect(
                    x: padding,
                    y: padding,
                    width: canvasSize.width - padding * 2,
                    height: canvasSize.height - padding * 2
                ),
                options: [.usesLineFragmentOrigin, .usesFontLeading],
                context: nil
            )
        }
        guard let cgImage = bitmap.cgImage else { return nil }
        return CIImage(cgImage: cgImage)
    }

    private func captionLayout(
        text: String,
        fontSize: CGFloat,
        maximumWidth: CGFloat
    ) -> (text: NSAttributedString, font: UIFont, bounds: CGRect) {
        let font = UIFont.systemFont(ofSize: fontSize, weight: .black)
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .center
        paragraph.lineBreakMode = .byWordWrapping
        let attributed = NSAttributedString(
            string: text,
            attributes: [
                .font: font,
                .foregroundColor: style.foreground.uiColor,
                .strokeColor: UIColor.black,
                .strokeWidth: -4.0,
                .paragraphStyle: paragraph,
            ]
        )
        let bounds = attributed.boundingRect(
            with: CGSize(width: maximumWidth, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            context: nil
        ).integral
        return (attributed, font, bounds)
    }
}

private final class CaptionImage: NSObject {
    let image: CIImage

    init(_ image: CIImage) {
        self.image = image
    }
}

extension SubtitleColor {
    fileprivate var uiColor: UIColor {
        switch self {
        case .yellow: .systemYellow
        case .white: .white
        case .cyan: .cyan
        }
    }
}
