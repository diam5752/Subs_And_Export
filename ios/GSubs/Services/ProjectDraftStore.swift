import AVFoundation
import Foundation

protocol ProjectDraftStoring: Sendable {
    func commitProject(
        ownerUserID: String,
        sourceURL: URL,
        previewURL: URL?,
        duration: Double,
        transcriptionKey: String,
        revision: UInt64
    ) async throws -> RestoredProjectDraft
    func save(_ draft: ProjectDraft) async throws
    func restore(ownerUserID: String) async throws -> RestoredProjectDraft?
    func lockImmediately(atRevision revision: UInt64)
    func purge(ifNewerThan revision: UInt64) async throws
    @discardableResult
    func purgeAll() async throws -> UInt64
}

actor ProjectDraftStore: ProjectDraftStoring {
    private nonisolated let currentURL: URL
    private let fileManager: FileManager
    private let appliesFileProtection: Bool
    private let validatesPlayableMedia: Bool
    private var highestRevision: UInt64 = 0

    init(
        currentURL: URL = LocalMediaStore.currentProjectURL,
        fileManager: FileManager = .default,
        appliesFileProtection: Bool = true,
        validatesPlayableMedia: Bool = true
    ) {
        self.currentURL = currentURL
        self.fileManager = fileManager
        self.appliesFileProtection = appliesFileProtection
        self.validatesPlayableMedia = validatesPlayableMedia
    }

    func commitProject(
        ownerUserID: String,
        sourceURL: URL,
        previewURL: URL?,
        duration: Double,
        transcriptionKey: String,
        revision: UInt64
    ) async throws -> RestoredProjectDraft {
        try validateInputFile(sourceURL)
        if let previewURL { try validateInputFile(previewURL) }
        try prepareParentDirectory()
        try claim(revision: revision)
        try clearRevocation(olderThan: revision)

        let stagingURL = currentURL.deletingLastPathComponent()
            .appendingPathComponent("Staging-\(UUID().uuidString)", isDirectory: true)
        let stagingMediaURL = mediaURL(for: stagingURL)
        try ensureDirectory(stagingURL)
        try ensureDirectory(stagingMediaURL)
        try applySecurity(to: stagingURL)
        try applySecurity(to: stagingMediaURL)
        let projectID = UUID()
        let sourcePath = relativeMediaPath(prefix: "source", sourceURL: sourceURL)
        let previewPath = previewURL.map {
            relativeMediaPath(prefix: "preview", sourceURL: $0, defaultExtension: "mp4")
        }
        let sourceDestination = try unresolvedURL(for: sourcePath, projectRoot: stagingURL)
        let previewDestination = try previewPath.map {
            try unresolvedURL(for: $0, projectRoot: stagingURL)
        }

        do {
            try copySecuredFile(from: sourceURL, to: sourceDestination)
            if let previewURL, let previewDestination {
                try copySecuredFile(from: previewURL, to: previewDestination)
            }
            let draft = ProjectDraft(
                projectID: projectID,
                revision: revision,
                ownerUserID: ownerUserID,
                sourceRelativePath: sourcePath,
                previewRelativePath: previewPath,
                duration: duration,
                cues: [],
                style: SubtitleStyle(),
                transcriptionKey: transcriptionKey,
                phase: .ready
            )
            try validateManifest(draft)
            let staged = try resolve(draft, projectRoot: stagingURL)
            try await validatePlayableMedia(staged)
            try writeManifest(draft, projectRoot: stagingURL)
            guard try revocationRevision() == nil,
                !fileManager.fileExists(atPath: currentURL.path)
            else {
                throw ProjectDraftError.staleRevision
            }
            try fileManager.moveItem(at: stagingURL, to: currentURL)
            return try resolve(draft)
        } catch {
            try? fileManager.removeItem(at: stagingURL)
            throw error
        }
    }

    func save(_ draft: ProjectDraft) throws {
        guard try revocationRevision() == nil else {
            throw ProjectDraftError.staleRevision
        }
        guard let current = try readManifest() else {
            throw ProjectDraftError.staleRevision
        }
        guard current.projectID == draft.projectID,
            current.ownerUserID == draft.ownerUserID,
            current.sourceRelativePath == draft.sourceRelativePath,
            current.previewRelativePath == draft.previewRelativePath
        else {
            throw ProjectDraftError.staleRevision
        }
        try claim(revision: draft.revision, diskRevision: current.revision)
        try validateManifest(draft)
        _ = try resolve(draft)
        try writeManifest(draft)
    }

    func restore(ownerUserID: String) async throws -> RestoredProjectDraft? {
        if try consumeRevocation() { return nil }
        guard let draft = try readManifest() else { return nil }
        try validateManifest(draft)
        guard draft.ownerUserID == ownerUserID else {
            throw ProjectDraftError.ownerMismatch
        }
        highestRevision = max(highestRevision, draft.revision)
        let restored = try resolve(draft)
        try await validatePlayableMedia(restored)
        try securePersistedFiles(restored)
        return restored
    }

    func purge(ifNewerThan revision: UInt64) throws {
        let diskRevision = try readManifest()?.revision ?? 0
        let revocation = try revocationRevision() ?? 0
        guard revision >= revocation,
            revision > max(highestRevision, diskRevision)
        else { return }
        highestRevision = revision
        try quarantineAndDeleteCurrent()
        try? fileManager.removeItem(at: revocationURL)
    }

    @discardableResult
    func purgeAll() throws -> UInt64 {
        let diskRevision = try readManifest()?.revision ?? 0
        let revocation = try revocationRevision() ?? 0
        let revisionFloor = max(highestRevision, diskRevision, revocation)
        highestRevision = revisionFloor == UInt64.max ? revisionFloor : revisionFloor + 1
        try quarantineAndDeleteCurrent()
        try? fileManager.removeItem(at: revocationURL)
        return highestRevision
    }

    nonisolated func lockImmediately(atRevision revision: UInt64) {
        let fileManager = FileManager.default
        let parent = currentURL.deletingLastPathComponent()
        try? fileManager.createDirectory(at: parent, withIntermediateDirectories: true)
        let marker = parent.appendingPathComponent("revoked", isDirectory: false)
        try? Data(String(revision).utf8).write(to: marker, options: .atomic)

        if fileManager.fileExists(atPath: currentURL.path) {
            let discarded = parent.appendingPathComponent(
                "Discarded-\(UUID().uuidString)",
                isDirectory: true
            )
            try? fileManager.moveItem(at: currentURL, to: discarded)
        }
        guard
            let urls = try? fileManager.contentsOfDirectory(
                at: parent,
                includingPropertiesForKeys: nil
            )
        else { return }
        for url in urls where url.lastPathComponent.hasPrefix("Staging-") {
            try? fileManager.removeItem(at: url)
        }
    }

    private var mediaURL: URL {
        mediaURL(for: currentURL)
    }

    private var manifestURL: URL {
        currentURL.appendingPathComponent("manifest.json", isDirectory: false)
    }

    private var revocationURL: URL {
        currentURL.deletingLastPathComponent()
            .appendingPathComponent("revoked", isDirectory: false)
    }

    private func prepareParentDirectory() throws {
        try removeDiscardedDirectories()
        try removeStagingDirectories()
        let parent = currentURL.deletingLastPathComponent()
        try ensureDirectory(parent)
        try applySecurity(to: parent)
    }

    private func ensureDirectory(_ url: URL) throws {
        if fileManager.fileExists(atPath: url.path) {
            let attributes = try fileManager.attributesOfItem(atPath: url.path)
            guard attributes[.type] as? FileAttributeType == .typeDirectory else {
                throw ProjectDraftError.corrupt
            }
            return
        }
        try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
    }

    private func claim(revision: UInt64, diskRevision: UInt64? = nil) throws {
        let storedRevision: UInt64
        if let diskRevision {
            storedRevision = diskRevision
        } else {
            storedRevision = try readManifest()?.revision ?? 0
        }
        let revocation = try revocationRevision() ?? 0
        guard revision > max(highestRevision, storedRevision, revocation) else {
            throw ProjectDraftError.staleRevision
        }
        highestRevision = revision
    }

    private func revocationRevision() throws -> UInt64? {
        guard fileManager.fileExists(atPath: revocationURL.path) else { return nil }
        try rejectSymbolicLink(revocationURL)
        let data = try Data(contentsOf: revocationURL)
        guard data.count <= 32,
            let value = String(data: data, encoding: .utf8),
            let revision = UInt64(value)
        else {
            throw ProjectDraftError.corrupt
        }
        return revision
    }

    private func clearRevocation(olderThan revision: UInt64) throws {
        guard let revokedRevision = try revocationRevision() else { return }
        guard revision > revokedRevision else { throw ProjectDraftError.staleRevision }
        try fileManager.removeItem(at: revocationURL)
    }

    private func consumeRevocation() throws -> Bool {
        guard let revision = try revocationRevision() else { return false }
        highestRevision = max(highestRevision, revision)
        try quarantineAndDeleteCurrent()
        try removeStagingDirectories()
        try? fileManager.removeItem(at: revocationURL)
        return true
    }

    private func validateManifest(_ draft: ProjectDraft) throws {
        try ProjectDraftValidator.validate(draft)
        try validateRelativePath(draft.sourceRelativePath)
        if let previewPath = draft.previewRelativePath {
            try validateRelativePath(previewPath)
            guard previewPath != draft.sourceRelativePath else {
                throw ProjectDraftError.corrupt
            }
        }
    }

    private func readManifest() throws -> ProjectDraft? {
        guard fileManager.fileExists(atPath: manifestURL.path) else { return nil }
        try rejectSymbolicLink(currentURL)
        try rejectSymbolicLink(manifestURL)
        let attributes = try fileManager.attributesOfItem(atPath: manifestURL.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
            let size = attributes[.size] as? NSNumber,
            size.intValue > 0,
            size.intValue <= ProjectDraftValidator.maximumManifestBytes
        else {
            throw ProjectDraftError.corrupt
        }
        do {
            return try JSONDecoder().decode(
                ProjectDraft.self,
                from: Data(contentsOf: manifestURL, options: .mappedIfSafe)
            )
        } catch let error as ProjectDraftError {
            throw error
        } catch {
            throw ProjectDraftError.corrupt
        }
    }

    private func writeManifest(
        _ draft: ProjectDraft,
        projectRoot: URL? = nil
    ) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(draft)
        guard data.count <= ProjectDraftValidator.maximumManifestBytes else {
            throw ProjectDraftError.corrupt
        }
        let destination = manifestURL(for: projectRoot ?? currentURL)
        try data.write(to: destination, options: .atomic)
        try applySecurity(to: destination)
    }

    private func resolve(
        _ draft: ProjectDraft,
        projectRoot: URL? = nil
    ) throws -> RestoredProjectDraft {
        let projectRoot = projectRoot ?? currentURL
        let sourceURL = try resolvedFile(
            for: draft.sourceRelativePath,
            required: true,
            projectRoot: projectRoot
        )!
        let previewURL: URL
        if let path = draft.previewRelativePath,
            let storedPreview = try resolvedFile(
                for: path,
                required: false,
                projectRoot: projectRoot
            )
        {
            previewURL = storedPreview
        } else {
            previewURL = sourceURL
        }
        return RestoredProjectDraft(
            draft: draft,
            sourceURL: sourceURL,
            previewURL: previewURL
        )
    }

    private func resolvedFile(
        for path: String,
        required: Bool,
        projectRoot: URL
    ) throws -> URL? {
        try validateRelativePath(path)
        try rejectSymbolicLink(projectRoot)
        try rejectSymbolicLink(mediaURL(for: projectRoot))
        let url = try unresolvedURL(for: path, projectRoot: projectRoot)
        guard fileManager.fileExists(atPath: url.path) else {
            if required { throw ProjectDraftError.corrupt }
            return nil
        }
        try rejectSymbolicLink(url)
        let attributes = try fileManager.attributesOfItem(atPath: url.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
            let size = attributes[.size] as? NSNumber,
            size.intValue > 0
        else {
            throw ProjectDraftError.corrupt
        }
        return url
    }

    private func unresolvedURL(for path: String, projectRoot: URL) throws -> URL {
        try validateRelativePath(path)
        let components = path.split(separator: "/").map(String.init)
        return components.reduce(projectRoot) { url, component in
            url.appendingPathComponent(component, isDirectory: false)
        }
    }

    private func validateRelativePath(_ path: String) throws {
        let components = path.split(separator: "/", omittingEmptySubsequences: false)
        guard components.count == 2,
            components[0] == "Media",
            !components[1].isEmpty,
            components.allSatisfy({ $0 != "." && $0 != ".." }),
            !path.hasPrefix("/"),
            !path.contains("\\")
        else {
            throw ProjectDraftError.corrupt
        }
    }

    private func validateInputFile(_ url: URL) throws {
        try rejectSymbolicLink(url)
        let attributes = try fileManager.attributesOfItem(atPath: url.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
            let size = attributes[.size] as? NSNumber,
            size.intValue > 0
        else {
            throw ProjectDraftError.corrupt
        }
    }

    private func rejectSymbolicLink(_ url: URL) throws {
        if (try? fileManager.destinationOfSymbolicLink(atPath: url.path)) != nil {
            throw ProjectDraftError.corrupt
        }
        guard fileManager.fileExists(atPath: url.path) else { return }
        let attributes = try fileManager.attributesOfItem(atPath: url.path)
        guard attributes[.type] as? FileAttributeType != .typeSymbolicLink else {
            throw ProjectDraftError.corrupt
        }
    }

    private func relativeMediaPath(
        prefix: String,
        sourceURL: URL,
        defaultExtension: String = "mov"
    ) -> String {
        let sourceExtension = sourceURL.pathExtension.lowercased()
        let validExtension =
            sourceExtension.count <= 12
            && !sourceExtension.isEmpty
            && sourceExtension.allSatisfy { $0.isLetter || $0.isNumber }
        let extensionName = validExtension ? sourceExtension : defaultExtension
        return "Media/\(prefix)-\(UUID().uuidString).\(extensionName)"
    }

    private func copySecuredFile(from source: URL, to destination: URL) throws {
        try fileManager.copyItem(at: source, to: destination)
        try validateInputFile(destination)
        try applySecurity(to: destination)
    }

    private func applySecurity(to url: URL) throws {
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var securedURL = url
        try securedURL.setResourceValues(values)
        guard appliesFileProtection else { return }
        try fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
    }

    private func securePersistedFiles(_ restored: RestoredProjectDraft) throws {
        try applySecurity(to: currentURL)
        try applySecurity(to: mediaURL)
        try applySecurity(to: manifestURL)
        try applySecurity(to: restored.sourceURL)
        if restored.previewURL != restored.sourceURL {
            try applySecurity(to: restored.previewURL)
        }
    }

    private func mediaURL(for projectRoot: URL) -> URL {
        projectRoot.appendingPathComponent("Media", isDirectory: true)
    }

    private func manifestURL(for projectRoot: URL) -> URL {
        projectRoot.appendingPathComponent("manifest.json", isDirectory: false)
    }

    private func validatePlayableMedia(_ restored: RestoredProjectDraft) async throws {
        guard validatesPlayableMedia else { return }
        try await validateVideo(
            at: restored.sourceURL,
            expectedDuration: restored.draft.duration
        )
        if restored.previewURL != restored.sourceURL {
            try await validateVideo(
                at: restored.previewURL,
                expectedDuration: restored.draft.duration
            )
        }
    }

    private func validateVideo(at url: URL, expectedDuration: Double) async throws {
        do {
            let asset = AVURLAsset(url: url)
            async let duration = asset.load(.duration).seconds
            async let tracks = asset.loadTracks(withMediaType: .video)
            let loadedDuration = try await duration
            let loadedTracks = try await tracks
            guard !loadedTracks.isEmpty,
                loadedDuration.isFinite,
                loadedDuration > 0,
                loadedDuration <= AudioExtractor.maximumDuration + 1,
                abs(loadedDuration - expectedDuration) <= 1
            else {
                throw ProjectDraftError.corrupt
            }
        } catch {
            throw ProjectDraftError.corrupt
        }
    }

    private func quarantineAndDeleteCurrent() throws {
        guard fileManager.fileExists(atPath: currentURL.path) else { return }
        let discardedURL = currentURL.deletingLastPathComponent()
            .appendingPathComponent("Discarded-\(UUID().uuidString)", isDirectory: true)
        do {
            try fileManager.moveItem(at: currentURL, to: discardedURL)
            try fileManager.removeItem(at: discardedURL)
        } catch {
            try? fileManager.removeItem(at: manifestURL)
            guard !fileManager.fileExists(atPath: manifestURL.path) else { throw error }
            try? fileManager.removeItem(at: currentURL)
        }
    }

    private func removeDiscardedDirectories() throws {
        let parent = currentURL.deletingLastPathComponent()
        guard fileManager.fileExists(atPath: parent.path) else { return }
        let urls = try fileManager.contentsOfDirectory(
            at: parent,
            includingPropertiesForKeys: nil
        )
        for url in urls where url.lastPathComponent.hasPrefix("Discarded-") {
            try? fileManager.removeItem(at: url)
        }
    }

    private func removeStagingDirectories() throws {
        let parent = currentURL.deletingLastPathComponent()
        guard fileManager.fileExists(atPath: parent.path) else { return }
        let urls = try fileManager.contentsOfDirectory(
            at: parent,
            includingPropertiesForKeys: nil
        )
        for url in urls where url.lastPathComponent.hasPrefix("Staging-") {
            try? fileManager.removeItem(at: url)
        }
    }
}
