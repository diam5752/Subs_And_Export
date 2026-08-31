#if DEBUG
    import Foundation

    struct UITestConfiguration: Sendable {
        let arguments: [String]

        static var current: UITestConfiguration {
            UITestConfiguration(arguments: ProcessInfo.processInfo.arguments)
        }

        var isEnabled: Bool {
            arguments.contains { $0.hasPrefix("--gsubs-ui-test-") }
        }

        var startsAuthenticated: Bool {
            arguments.contains("--gsubs-ui-test-authenticated")
                || arguments.contains("--gsubs-ui-test-delete-failure")
                || arguments.contains("--gsubs-ui-test-slow-delete-editor")
                || arguments.contains("--gsubs-ui-test-slow-delete-empty")
                || startsWithVideo
        }

        var startsWithVideo: Bool {
            arguments.contains("--gsubs-ui-test-ready")
                || arguments.contains("--gsubs-ui-test-editor")
                || arguments.contains("--gsubs-ui-test-export-failure")
                || arguments.contains("--gsubs-ui-test-slow-export")
                || arguments.contains("--gsubs-ui-test-slow-delete-editor")
                || arguments.contains("--gsubs-ui-test-transcription-failure")
        }

        var startsEditing: Bool {
            arguments.contains("--gsubs-ui-test-editor")
                || arguments.contains("--gsubs-ui-test-export-failure")
                || arguments.contains("--gsubs-ui-test-slow-export")
                || arguments.contains("--gsubs-ui-test-slow-delete-editor")
        }

        var failsAuthentication: Bool {
            arguments.contains("--gsubs-ui-test-auth-failure")
        }

        var failsTranscription: Bool {
            arguments.contains("--gsubs-ui-test-transcription-failure")
        }

        var failsAccountDeletion: Bool {
            arguments.contains("--gsubs-ui-test-delete-failure")
        }

        var delaysAccountDeletion: Bool {
            arguments.contains("--gsubs-ui-test-slow-delete-editor")
                || arguments.contains("--gsubs-ui-test-slow-delete-empty")
        }

        var failsExport: Bool {
            arguments.contains("--gsubs-ui-test-export-failure")
        }

        var delaysExport: Bool {
            arguments.contains("--gsubs-ui-test-slow-export")
        }
    }

    struct UITestFailingVideoExporter: VideoExporting {
        func export(
            videoURL: URL,
            cues: [SubtitleCue],
            style: SubtitleStyle
        ) async throws -> URL {
            try await Task.sleep(for: .milliseconds(180))
            throw LocalMediaError.cannotExport
        }
    }

    struct UITestDelayedVideoExporter: VideoExporting {
        func export(
            videoURL: URL,
            cues: [SubtitleCue],
            style: SubtitleStyle
        ) async throws -> URL {
            try await Task.sleep(for: .seconds(8))
            let destination = try LocalMediaStore.directory(named: "Exports")
                .appendingPathComponent("GSubs-UITest-\(UUID().uuidString)")
                .appendingPathExtension("mp4")
            do {
                try FileManager.default.copyItem(at: videoURL, to: destination)
                try Task.checkCancellation()
                return destination
            } catch {
                try? FileManager.default.removeItem(at: destination)
                throw error
            }
        }
    }

    actor UITestAPIClient: GSubsAPIClient {
        private let configuration: UITestConfiguration
        private var balance = 100

        init(configuration: UITestConfiguration) {
            self.configuration = configuration
        }

        func login(email: String, password: String) async throws -> LoginResult {
            try await simulatedDelay()
            if configuration.failsAuthentication {
                throw APIError(status: 401, message: "Λάθος email ή κωδικός.")
            }
            return LoginResult(
                accessToken: "ios-ui-test-token",
                tokenType: "bearer",
                userId: "ios-ui-test",
                name: "iOS QA",
                betaCreditsAwarded: 0
            )
        }

        func register(email: String, password: String, name: String) async throws {
            try await simulatedDelay()
            if configuration.failsAuthentication {
                throw APIError(status: 422, message: "Δεν ήταν δυνατή η εγγραφή.")
            }
        }

        func profile(token: String) async throws -> UserProfile {
            UserProfile(
                id: "ios-ui-test",
                email: "ios-ui-test@gsubs.local",
                name: "iOS QA",
                provider: "local"
            )
        }

        func points(token: String) async throws -> PointsBalance {
            PointsBalance(
                balance: balance,
                paidBalance: balance,
                promotionalBalance: 0,
                reversalDebt: 0,
                aiSpendableBalance: balance
            )
        }

        func logout(token: String) async {}

        func deleteAccount(token: String) async throws {
            if configuration.delaysAccountDeletion {
                try await Task.sleep(for: .seconds(8))
                return
            }
            try await simulatedDelay()
            if configuration.failsAccountDeletion {
                throw APIError(status: 503, message: "Η διαγραφή δεν ολοκληρώθηκε. Δοκίμασε ξανά.")
            }
        }

        func transcribe(
            audioURL: URL,
            token: String,
            idempotencyKey: String
        ) async throws -> MobileTranscriptionResult {
            try await simulatedDelay()
            guard FileManager.default.fileExists(atPath: audioURL.path) else {
                throw APIError(status: 400, message: "Ο ήχος δεν βρέθηκε.")
            }
            if configuration.failsTranscription {
                throw APIError(status: 503, message: "Η μεταγραφή δεν είναι προσωρινά διαθέσιμη.")
            }
            balance = 70
            return MobileTranscriptionResult(
                requestId: "ios-ui-test-transcription",
                durationSeconds: 4,
                creditsCharged: 30,
                balance: balance,
                videoUploaded: false,
                serverMediaRetained: false,
                cues: Self.sampleCues
            )
        }

        private func simulatedDelay() async throws {
            try await Task.sleep(for: .milliseconds(180))
        }

        static let sampleCues = [
            SubtitleCue(start: 0.2, end: 1.3, text: "ΤΟ ΒΙΝΤΕΟ ΜΕΝΕΙ ΣΤΟ IPHONE", words: []),
            SubtitleCue(start: 1.4, end: 2.6, text: "ΟΙ ΥΠΟΤΙΤΛΟΙ ΕΡΧΟΝΤΑΙ ΕΤΟΙΜΟΙ", words: []),
            SubtitleCue(start: 2.7, end: 3.9, text: "ΤΟ EXPORT ΓΙΝΕΤΑΙ ΤΟΠΙΚΑ", words: []),
        ]
    }
#endif
