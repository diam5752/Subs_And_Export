import CoreTransferable
import Foundation
import UniformTypeIdentifiers

struct PickedVideo: Transferable, Sendable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .movie) { received in
            let directory = try LocalMediaStore.temporaryDirectory(named: "Incoming")
            let extensionName = received.file.pathExtension.isEmpty ? "mov" : received.file.pathExtension
            let destination =
                directory
                .appendingPathComponent(UUID().uuidString)
                .appendingPathExtension(extensionName)
            try FileManager.default.copyItem(at: received.file, to: destination)
            return PickedVideo(url: destination)
        }
    }
}
