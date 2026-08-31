import AVFoundation
import Foundation

enum LocalMediaError: LocalizedError {
    case missingVideo
    case missingAudio
    case invalidDuration
    case tooLong
    case cannotExport
    case cannotDecodeExport
    case photoPermission

    var errorDescription: String? {
        switch self {
        case .missingVideo: "Το αρχείο δεν περιέχει αναγνώσιμο βίντεο."
        case .missingAudio: "Το βίντεο δεν περιέχει ήχο για μεταγραφή."
        case .invalidDuration: "Δεν ήταν δυνατή η ανάγνωση της διάρκειας."
        case .tooLong: "Η πρώτη έκδοση υποστηρίζει βίντεο έως 3 λεπτά."
        case .cannotExport: "Η τοπική εξαγωγή δεν ολοκληρώθηκε."
        case .cannotDecodeExport: "Το τελικό MP4 δεν πέρασε τον έλεγχο αναπαραγωγής."
        case .photoPermission: "Χρειάζεται άδεια για αποθήκευση στις Φωτογραφίες."
        }
    }
}

protocol AudioExtracting: Sendable {
    func duration(of videoURL: URL) async throws -> Double
    func extract(from videoURL: URL) async throws -> URL
}

struct AudioExtractor {
    static let maximumDuration = 180.0

    func duration(of videoURL: URL) async throws -> Double {
        try Task.checkCancellation()
        let asset = AVURLAsset(url: videoURL)
        let duration = try await asset.load(.duration).seconds
        try Task.checkCancellation()
        guard duration.isFinite, duration > 0 else { throw LocalMediaError.invalidDuration }
        guard duration <= Self.maximumDuration else { throw LocalMediaError.tooLong }
        guard try await !asset.loadTracks(withMediaType: .video).isEmpty else {
            throw LocalMediaError.missingVideo
        }
        return duration
    }

    func extract(from videoURL: URL) async throws -> URL {
        try Task.checkCancellation()
        let asset = AVURLAsset(url: videoURL)
        _ = try await duration(of: videoURL)
        guard try await !asset.loadTracks(withMediaType: .audio).isEmpty else {
            throw LocalMediaError.missingAudio
        }
        try Task.checkCancellation()
        guard
            let exporter = AVAssetExportSession(
                asset: asset,
                presetName: AVAssetExportPresetAppleM4A
            )
        else { throw LocalMediaError.cannotExport }
        let destination = temporaryURL(extension: "m4a", folder: "Audio")
        try? FileManager.default.removeItem(at: destination)
        exporter.outputURL = destination
        exporter.outputFileType = .m4a
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
        return destination
    }

    private func temporaryURL(extension extensionName: String, folder: String) -> URL {
        let directory =
            (try? LocalMediaStore.temporaryDirectory(named: folder))
            ?? FileManager.default.temporaryDirectory
        return directory.appendingPathComponent(UUID().uuidString).appendingPathExtension(extensionName)
    }
}

extension AudioExtractor: AudioExtracting {}

extension AVAssetExportSession {
    func run() async {
        let box = ExportSessionBox(self)
        await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                box.session.exportAsynchronously { continuation.resume() }
            }
        } onCancel: {
            box.session.cancelExport()
        }
    }
}

private final class ExportSessionBox: @unchecked Sendable {
    let session: AVAssetExportSession

    init(_ session: AVAssetExportSession) {
        self.session = session
    }
}
