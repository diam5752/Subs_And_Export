import AVFoundation
import CoreImage
import CoreVideo
import XCTest
@testable import GSubs

final class VideoExporterTests: XCTestCase {
    func testSubtitleRendererProducesVisibleBitmap() throws {
        let cues = [SubtitleCue(start: 0.1, end: 0.9, text: "ΤΟΠΙΚΟ EXPORT", words: [])]
        let image = try XCTUnwrap(
            SubtitleFrameRenderer(cues: cues, style: SubtitleStyle()).caption(
                at: 0.5,
                frameExtent: CGRect(x: 0, y: 0, width: 320, height: 568)
            )
        )
        let bitmap = try XCTUnwrap(CIContext().createCGImage(image, from: image.extent))
        XCTAssertGreaterThan(image.extent.width, 10)
        XCTAssertGreaterThan(image.extent.height, 10)
        XCTAssertGreaterThan(try brightPixelCount(in: bitmap), 100)
    }

    func testExportProducesADecodableLocalMP4() async throws {
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("mp4")
        defer { try? FileManager.default.removeItem(at: source) }
        try await makeVideo(at: source)
        let cues = [SubtitleCue(start: 0.1, end: 0.9, text: "ΤΟΠΙΚΟ EXPORT", words: [])]
        XCTAssertNotNil(
            SubtitleFrameRenderer(cues: cues, style: SubtitleStyle()).caption(
                at: 0.5,
                frameExtent: CGRect(x: 0, y: 0, width: 320, height: 568)
            )
        )

        let output = try await VideoExporter().export(
            videoURL: source,
            cues: cues,
            style: SubtitleStyle()
        )
        defer { try? FileManager.default.removeItem(at: output) }

        let asset = AVURLAsset(url: output)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        let duration = try await asset.load(.duration).seconds
        XCTAssertFalse(tracks.isEmpty)
        XCTAssertGreaterThan(duration, 0.9)
        XCTAssertGreaterThan(try Data(contentsOf: output).count, 1_000)
        XCTAssertGreaterThan(try brightPixelCount(in: asset, at: 0.5), 100)
    }

    private func makeVideo(at url: URL) async throws {
        let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)
        let input = AVAssetWriterInput(
            mediaType: .video,
            outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264,
                AVVideoWidthKey: 320,
                AVVideoHeightKey: 568
            ]
        )
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: 320,
                kCVPixelBufferHeightKey as String: 568,
                kCVPixelBufferIOSurfacePropertiesKey as String: [:]
            ]
        )
        XCTAssertTrue(writer.canAdd(input))
        writer.add(input)
        XCTAssertTrue(writer.startWriting())
        writer.startSession(atSourceTime: .zero)
        for frame in 0..<30 {
            while !input.isReadyForMoreMediaData {
                try await Task.sleep(for: .milliseconds(2))
            }
            guard let pool = adaptor.pixelBufferPool else {
                XCTFail("Pixel buffer pool was unavailable")
                return
            }
            var optionalBuffer: CVPixelBuffer?
            CVPixelBufferPoolCreatePixelBuffer(nil, pool, &optionalBuffer)
            guard let buffer = optionalBuffer else {
                XCTFail("Pixel buffer allocation failed")
                return
            }
            fill(buffer, frame: frame)
            XCTAssertTrue(adaptor.append(buffer, withPresentationTime: CMTime(value: Int64(frame), timescale: 30)))
        }
        input.markAsFinished()
        await withCheckedContinuation { continuation in
            writer.finishWriting { continuation.resume() }
        }
        if writer.status != .completed {
            throw writer.error ?? LocalMediaError.cannotExport
        }
    }

    private func fill(_ buffer: CVPixelBuffer, frame: Int) {
        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return }
        memset(base, Int32(40 + frame), CVPixelBufferGetDataSize(buffer))
    }

    private func brightPixelCount(in asset: AVAsset, at seconds: Double) throws -> Int {
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.requestedTimeToleranceBefore = .zero
        generator.requestedTimeToleranceAfter = .zero
        var actualTime = CMTime.invalid
        let image = try generator.copyCGImage(
            at: CMTime(seconds: seconds, preferredTimescale: 600),
            actualTime: &actualTime
        )
        XCTAssertEqual(actualTime.seconds, seconds, accuracy: 1.0 / 30.0)
        return try brightPixelCount(in: image)
    }

    private func brightPixelCount(in image: CGImage) throws -> Int {
        let width = image.width
        let height = image.height
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        try pixels.withUnsafeMutableBytes { bytes in
            let context = try XCTUnwrap(CGContext(
                data: bytes.baseAddress,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ))
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        }
        return stride(from: 0, to: pixels.count, by: 4).reduce(into: 0) { count, offset in
            let colors = [pixels[offset], pixels[offset + 1], pixels[offset + 2]]
            if colors.max() ?? 0 > 120 {
                count += 1
            }
        }
    }
}
