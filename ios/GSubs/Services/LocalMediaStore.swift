import Foundation

enum LocalMediaStore {
    static var temporaryRootURL: URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("GSubs", isDirectory: true)
    }

    static var currentProjectURL: URL {
        let applicationSupport =
            FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first ?? FileManager.default.temporaryDirectory
        return
            applicationSupport
            .appendingPathComponent("GSubs", isDirectory: true)
            .appendingPathComponent("Current", isDirectory: true)
    }

    static func temporaryDirectory(named name: String) throws -> URL {
        let directory = temporaryRootURL.appendingPathComponent(name, isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        return directory
    }

    static func directory(named name: String) throws -> URL {
        try temporaryDirectory(named: name)
    }

    static func cleanupStaleMediaAtLaunch() {
        let staleURLs = quarantineStaleMedia(at: temporaryRootURL)
        guard !staleURLs.isEmpty else { return }

        Task.detached(priority: .utility) {
            for url in staleURLs {
                try? FileManager.default.removeItem(at: url)
            }
        }
    }

    static func quarantineStaleMedia(
        at root: URL,
        fileManager: FileManager = .default
    ) -> [URL] {
        let parent = root.deletingLastPathComponent()
        let stalePrefix = "\(root.lastPathComponent)-Stale-"
        var staleURLs =
            (try? fileManager.contentsOfDirectory(
                at: parent,
                includingPropertiesForKeys: nil
            ))?.filter { $0.lastPathComponent.hasPrefix(stalePrefix) } ?? []

        guard fileManager.fileExists(atPath: root.path) else { return staleURLs }
        let quarantineURL = parent.appendingPathComponent(
            "\(stalePrefix)\(UUID().uuidString)",
            isDirectory: true
        )

        do {
            try fileManager.moveItem(at: root, to: quarantineURL)
            staleURLs.append(quarantineURL)
        } catch {
            // Leaving old media in place is safer than racing a new project.
        }
        return staleURLs
    }
}
