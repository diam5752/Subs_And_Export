import AVFoundation
import AudioToolbox
import CoreImage
import CoreMedia
import CoreVideo
import XCTest

@testable import GSubs

final class VideoExporterTests: XCTestCase {
    func testSubtitleRendererProducesVisibleBitmap() throws {
        let cues = [
            SubtitleCue(
                start: 0.1,
                end: 0.9,
                text: "ΤΟΠΙΚΟ EXPORT ΜΕ ΜΕΓΑΛΟ ΕΛΛΗΝΙΚΟ ΥΠΟΤΙΤΛΟ ΣΕ ΠΟΛΛΕΣ ΓΡΑΜΜΕΣ",
                words: []
            )
        ]
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

    func testSubtitleRendererWrapsLongCaptionsWithoutLeavingTheFrame() throws {
        let shortCue = SubtitleCue(start: 0, end: 1, text: "ΜΙΚΡΟ", words: [])
        let longCue = SubtitleCue(
            start: 0,
            end: 1,
            text: "ΑΥΤΟΣ ΕΙΝΑΙ ΕΝΑΣ ΜΕΓΑΛΥΤΕΡΟΣ ΕΛΛΗΝΙΚΟΣ ΥΠΟΤΙΤΛΟΣ ΠΟΥ ΠΡΕΠΕΙ ΝΑ ΣΠΑΕΙ ΣΕ ΓΡΑΜΜΕΣ",
            words: []
        )
        let extent = CGRect(x: 0, y: 0, width: 320, height: 568)
        let shortImage = try XCTUnwrap(
            SubtitleFrameRenderer(cues: [shortCue], style: SubtitleStyle()).caption(
                at: 0.5,
                frameExtent: extent
            )
        )
        let longImage = try XCTUnwrap(
            SubtitleFrameRenderer(cues: [longCue], style: SubtitleStyle()).caption(
                at: 0.5,
                frameExtent: extent
            )
        )

        XCTAssertGreaterThan(longImage.extent.height, shortImage.extent.height + 18)
        XCTAssertLessThanOrEqual(longImage.extent.width, extent.width * 0.89)
        XCTAssertTrue(extent.contains(longImage.extent))

        var highStyle = SubtitleStyle()
        highStyle.bottomOffset = 0.72
        let landscapeExtent = CGRect(x: 0, y: 0, width: 568, height: 320)
        let highImage = try XCTUnwrap(
            SubtitleFrameRenderer(cues: [longCue], style: highStyle).caption(
                at: 0.5,
                frameExtent: landscapeExtent
            )
        )
        XCTAssertTrue(landscapeExtent.contains(highImage.extent))
    }

    func testSubtitleRendererMovesOnlyTheCueWithAPositionOverride() throws {
        let commonText = "ΙΔΙΑ ΦΡΑΣΗ"
        let first = SubtitleCue(start: 0, end: 1, text: commonText, words: [])
        var selected = SubtitleCue(start: 1, end: 2, text: commonText, words: [])
        let last = SubtitleCue(start: 2, end: 3, text: commonText, words: [])
        selected.bottomOffsetOverride = 0.48

        var style = SubtitleStyle()
        style.bottomOffset = 0.2
        let baselineRenderer = SubtitleFrameRenderer(
            cues: [first, SubtitleCue(start: 1, end: 2, text: commonText, words: []), last],
            style: style
        )
        let overriddenRenderer = SubtitleFrameRenderer(cues: [first, selected, last], style: style)

        for frameExtent in [
            CGRect(x: 0, y: 0, width: 320, height: 568),
            CGRect(x: 0, y: 0, width: 568, height: 320),
        ] {
            let baselineFrames = try [0.5, 1.5, 2.5].map { time in
                try XCTUnwrap(baselineRenderer.caption(at: time, frameExtent: frameExtent))
            }
            let overriddenFrames = try [0.5, 1.5, 2.5].map { time in
                try XCTUnwrap(overriddenRenderer.caption(at: time, frameExtent: frameExtent))
            }

            XCTAssertEqual(overriddenFrames[0].extent, baselineFrames[0].extent)
            XCTAssertEqual(overriddenFrames[2].extent, baselineFrames[2].extent)
            assertSharedPlacement(
                frame: overriddenFrames[0],
                frameExtent: frameExtent,
                bottomOffset: style.resolvedBottomOffset(for: first)
            )
            assertSharedPlacement(
                frame: overriddenFrames[2],
                frameExtent: frameExtent,
                bottomOffset: style.resolvedBottomOffset(for: last)
            )

            assertSharedPlacement(
                frame: baselineFrames[1],
                frameExtent: frameExtent,
                bottomOffset: style.resolvedBottomOffset(for: first)
            )
            assertSharedPlacement(
                frame: overriddenFrames[1],
                frameExtent: frameExtent,
                bottomOffset: style.resolvedBottomOffset(for: selected)
            )
            XCTAssertEqual(
                overriddenFrames[1].extent.minX,
                baselineFrames[1].extent.minX,
                accuracy: 0.01
            )
            XCTAssertEqual(
                overriddenFrames[1].extent.width,
                baselineFrames[1].extent.width,
                accuracy: 0.01
            )
            XCTAssertEqual(
                overriddenFrames[1].extent.height,
                baselineFrames[1].extent.height,
                accuracy: 1
            )
            XCTAssertGreaterThan(
                overriddenFrames[1].extent.minY - baselineFrames[1].extent.minY,
                frameExtent.height * 0.2
            )
        }
    }

    func testVerificationFailureDeletesTheCreatedExport() async throws {
        let output = FileManager.default.temporaryDirectory
            .appendingPathComponent("InvalidExport-\(UUID().uuidString)")
            .appendingPathExtension("mp4")
        try Data("not-a-video".utf8).write(to: output)

        do {
            _ = try await VideoExporter.validatedExport(at: output)
            XCTFail("Expected export verification to fail")
        } catch {
            // Expected: an invalid candidate cannot be returned to the user.
        }

        XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))
    }

    func testCancellationDuringVerificationDeletesTheCreatedExport() async throws {
        let output = FileManager.default.temporaryDirectory
            .appendingPathComponent("CancelledExport-\(UUID().uuidString)")
            .appendingPathExtension("mp4")
        try Data("pending-export".utf8).write(to: output)
        let verification = Task {
            try await VideoExporter.validatedExport(at: output)
        }
        verification.cancel()

        do {
            _ = try await verification.value
            XCTFail("Expected export verification cancellation")
        } catch is CancellationError {
            // Expected.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))
    }

    func testExportProducesADecodableLocalMP4() async throws {
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("mp4")
        defer { try? FileManager.default.removeItem(at: source) }
        try await makeVideo(at: source)
        let sourceAsset = AVURLAsset(url: source)
        let sourceVideoDuration = try await videoTrackDuration(in: sourceAsset)
        try await assertDecodableAACAudio(
            in: sourceAsset,
            matchingVideoDuration: sourceVideoDuration
        )
        let cues = [
            SubtitleCue(
                start: 0.1,
                end: 0.9,
                text: "ΤΟΠΙΚΟ EXPORT ΜΕ ΜΕΓΑΛΟ ΕΛΛΗΝΙΚΟ ΥΠΟΤΙΤΛΟ ΣΕ ΠΟΛΛΕΣ ΓΡΑΜΜΕΣ",
                words: []
            )
        ]
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

        let exportedAsset = AVURLAsset(url: output)
        let videoTracks = try await exportedAsset.loadTracks(withMediaType: .video)
        let duration = try await exportedAsset.load(.duration).seconds
        let exportedVideoDuration = try await videoTrackDuration(in: exportedAsset)
        XCTAssertFalse(videoTracks.isEmpty)
        XCTAssertGreaterThan(duration, 0.9)
        XCTAssertEqual(exportedVideoDuration, sourceVideoDuration, accuracy: 0.1)
        try await assertDecodableAACAudio(
            in: exportedAsset,
            matchingVideoDuration: exportedVideoDuration
        )
        XCTAssertGreaterThan(try Data(contentsOf: output).count, 1_000)
        XCTAssertGreaterThan(try brightPixelCount(in: exportedAsset, at: 0.5), 100)
    }

    private func makeVideo(at url: URL) async throws {
        let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)
        let input = AVAssetWriterInput(
            mediaType: .video,
            outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264,
                AVVideoWidthKey: 320,
                AVVideoHeightKey: 568,
            ]
        )
        let audioInput = AVAssetWriterInput(
            mediaType: .audio,
            outputSettings: [
                AVFormatIDKey: kAudioFormatMPEG4AAC,
                AVSampleRateKey: 44_100,
                AVNumberOfChannelsKey: 1,
                AVEncoderBitRateKey: 64_000,
            ]
        )
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: 320,
                kCVPixelBufferHeightKey as String: 568,
                kCVPixelBufferIOSurfacePropertiesKey as String: [:],
            ]
        )
        XCTAssertTrue(writer.canAdd(input))
        writer.add(input)
        XCTAssertTrue(writer.canAdd(audioInput))
        writer.add(audioInput)
        XCTAssertTrue(writer.startWriting())
        writer.startSession(atSourceTime: .zero)
        while !audioInput.isReadyForMoreMediaData {
            try await Task.sleep(for: .milliseconds(2))
        }
        XCTAssertTrue(
            audioInput.append(
                try makePCMAudioSampleBuffer(
                    sampleRate: 44_100,
                    frameCount: 44_100
                )))
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
        audioInput.markAsFinished()
        await withCheckedContinuation { continuation in
            writer.finishWriting { continuation.resume() }
        }
        if writer.status != .completed {
            throw writer.error ?? LocalMediaError.cannotExport
        }
    }

    private func videoTrackDuration(in asset: AVURLAsset) async throws -> Double {
        let videoTracks = try await asset.loadTracks(withMediaType: .video)
        let videoTrack = try XCTUnwrap(videoTracks.first)
        return try await videoTrack.load(.timeRange).duration.seconds
    }

    private func assertDecodableAACAudio(
        in asset: AVURLAsset,
        matchingVideoDuration videoDuration: Double,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        let audioTracks = try await asset.loadTracks(withMediaType: .audio)
        let audioTrack = try XCTUnwrap(
            audioTracks.first,
            "Expected one AAC audio track",
            file: file,
            line: line
        )
        let formatDescriptions = try await audioTrack.load(.formatDescriptions)
        XCTAssertTrue(
            formatDescriptions.contains {
                CMFormatDescriptionGetMediaSubType($0) == kAudioFormatMPEG4AAC
            },
            "Expected the MP4 audio track to use AAC",
            file: file,
            line: line
        )

        let audioDuration = try await audioTrack.load(.timeRange).duration.seconds
        XCTAssertTrue(audioDuration.isFinite, file: file, line: line)
        XCTAssertGreaterThan(audioDuration, 0, file: file, line: line)
        XCTAssertEqual(
            audioDuration,
            videoDuration,
            accuracy: 0.1,
            "Audio duration must remain aligned with video duration",
            file: file,
            line: line
        )

        let reader = try AVAssetReader(asset: asset)
        let decodedAudio = AVAssetReaderTrackOutput(
            track: audioTrack,
            outputSettings: [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
            ]
        )
        XCTAssertTrue(reader.canAdd(decodedAudio), file: file, line: line)
        reader.add(decodedAudio)
        XCTAssertTrue(
            reader.startReading(),
            reader.error?.localizedDescription ?? "Audio reader did not start",
            file: file,
            line: line
        )
        let decodedSample = decodedAudio.copyNextSampleBuffer()
        XCTAssertNotNil(
            decodedSample,
            reader.error?.localizedDescription ?? "AAC track produced no decoded PCM",
            file: file,
            line: line
        )
        if let decodedSample {
            XCTAssertGreaterThan(
                CMSampleBufferGetNumSamples(decodedSample),
                0,
                file: file,
                line: line
            )
        }
        XCTAssertNotEqual(reader.status, .failed, file: file, line: line)
        reader.cancelReading()
    }

    private func makePCMAudioSampleBuffer(
        sampleRate: Int32,
        frameCount: Int
    ) throws -> CMSampleBuffer {
        let bytesPerFrame = MemoryLayout<Int16>.size
        let samples = (0..<frameCount).map { sampleIndex in
            (sampleIndex / 50).isMultiple(of: 2) ? Int16(6_000) : Int16(-6_000)
        }
        let dataLength = samples.count * bytesPerFrame

        var blockBuffer: CMBlockBuffer?
        let blockStatus = CMBlockBufferCreateWithMemoryBlock(
            allocator: kCFAllocatorDefault,
            memoryBlock: nil,
            blockLength: dataLength,
            blockAllocator: kCFAllocatorDefault,
            customBlockSource: nil,
            offsetToData: 0,
            dataLength: dataLength,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        try requireNoError(blockStatus, operation: "allocate PCM block buffer")
        let resolvedBlockBuffer = try XCTUnwrap(blockBuffer)
        let copyStatus = samples.withUnsafeBytes { bytes in
            CMBlockBufferReplaceDataBytes(
                with: bytes.baseAddress!,
                blockBuffer: resolvedBlockBuffer,
                offsetIntoDestination: 0,
                dataLength: dataLength
            )
        }
        try requireNoError(copyStatus, operation: "copy PCM samples")

        var streamDescription = AudioStreamBasicDescription(
            mSampleRate: Double(sampleRate),
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked,
            mBytesPerPacket: UInt32(bytesPerFrame),
            mFramesPerPacket: 1,
            mBytesPerFrame: UInt32(bytesPerFrame),
            mChannelsPerFrame: 1,
            mBitsPerChannel: 16,
            mReserved: 0
        )
        var formatDescription: CMAudioFormatDescription?
        let formatStatus = CMAudioFormatDescriptionCreate(
            allocator: kCFAllocatorDefault,
            asbd: &streamDescription,
            layoutSize: 0,
            layout: nil,
            magicCookieSize: 0,
            magicCookie: nil,
            extensions: nil,
            formatDescriptionOut: &formatDescription
        )
        try requireNoError(formatStatus, operation: "create PCM format description")

        var timing = CMSampleTimingInfo(
            duration: CMTime(value: 1, timescale: sampleRate),
            presentationTimeStamp: .zero,
            decodeTimeStamp: .invalid
        )
        var sampleSize = bytesPerFrame
        var sampleBuffer: CMSampleBuffer?
        let sampleStatus = CMSampleBufferCreate(
            allocator: kCFAllocatorDefault,
            dataBuffer: resolvedBlockBuffer,
            dataReady: true,
            makeDataReadyCallback: nil,
            refcon: nil,
            formatDescription: try XCTUnwrap(formatDescription),
            sampleCount: frameCount,
            sampleTimingEntryCount: 1,
            sampleTimingArray: &timing,
            sampleSizeEntryCount: 1,
            sampleSizeArray: &sampleSize,
            sampleBufferOut: &sampleBuffer
        )
        try requireNoError(sampleStatus, operation: "create PCM sample buffer")
        return try XCTUnwrap(sampleBuffer)
    }

    private func requireNoError(_ status: OSStatus, operation: String) throws {
        guard status == noErr else {
            throw NSError(
                domain: "VideoExporterTests",
                code: Int(status),
                userInfo: [NSLocalizedDescriptionKey: "Failed to \(operation): \(status)"]
            )
        }
    }

    private func assertSharedPlacement(
        frame: CIImage,
        frameExtent: CGRect,
        bottomOffset: Double,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let expectedBottomEdge = SubtitlePlacement.bottomEdgeFromBottom(
            frameHeight: frameExtent.height,
            captionHeight: frame.extent.height,
            bottomOffset: bottomOffset
        )
        let previewCenterY = SubtitlePlacement.centerYFromTop(
            frameHeight: frameExtent.height,
            captionHeight: frame.extent.height,
            bottomOffset: bottomOffset
        )
        let previewBottomEdge = frameExtent.height - previewCenterY - frame.extent.height / 2

        // Core Image aligns the rendered bitmap extent to whole pixels. Both
        // preview and export still resolve the same bottom edge to within one pixel.
        XCTAssertEqual(
            frame.extent.minY - frameExtent.minY,
            expectedBottomEdge,
            accuracy: 1,
            file: file,
            line: line
        )
        XCTAssertEqual(
            frame.extent.minY - frameExtent.minY,
            previewBottomEdge,
            accuracy: 1,
            file: file,
            line: line
        )
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
            let context = try XCTUnwrap(
                CGContext(
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
