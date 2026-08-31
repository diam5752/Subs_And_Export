import Foundation
import XCTest

@testable import GSubs

final class APIClientTests: XCTestCase {
    override func tearDown() {
        URLProtocolStub.handler = nil
        super.tearDown()
    }

    #if DEBUG
        func testDebugBaseURLOverrideAcceptsOnlyHTTPAndFallsBackSafely() {
            let local = APIClient.configuredBaseURL(
                debugOverride: " http://localhost:8080 ",
                plistValue: "https://gsubs.gr"
            )
            let unsafeOverride = APIClient.configuredBaseURL(
                debugOverride: "file:///tmp/gsubs",
                plistValue: "https://gsubs.gr"
            )
            let missingHost = APIClient.configuredBaseURL(
                debugOverride: "http:///missing-host",
                plistValue: "https://gsubs.gr"
            )
            let invalidPlist = APIClient.configuredBaseURL(
                debugOverride: "javascript:alert(1)",
                plistValue: "not-a-url"
            )

            XCTAssertEqual(local.absoluteString, "http://localhost:8080")
            XCTAssertEqual(unsafeOverride.absoluteString, "https://gsubs.gr")
            XCTAssertEqual(missingHost.absoluteString, "https://gsubs.gr")
            XCTAssertEqual(invalidPlist.absoluteString, "https://gsubs.gr")
        }
    #endif

    func testTranscriptionSendsOnlyAudioToTheMobileEndpoint() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let client = APIClient(baseURL: URL(string: "https://example.test")!, session: session)
        let audioURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("m4a")
        try Data("audio-only".utf8).write(to: audioURL)
        defer { try? FileManager.default.removeItem(at: audioURL) }
        let constructedRequest = client.mobileTranscriptionRequest(
            audio: Data("audio-only".utf8),
            token: "session-token",
            idempotencyKey: "00000000-0000-4000-8000-000000000000"
        )
        XCTAssertEqual(constructedRequest.httpBody, Data("audio-only".utf8))
        URLProtocolStub.handler = { request in
            XCTAssertEqual(request.url?.path, "/videos/mobile-transcriptions")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "audio/mp4")
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Gsubs-Authorized-Credits"), "30")
            let body =
                #"{"request_id":"mobile-1","duration_seconds":2,"credits_charged":30,"balance":70,"paid_balance":50,"promotional_balance":20,"reversal_debt":0,"ai_spendable_balance":50,"video_uploaded":false,"server_media_retained":false,"cues":[]}"#
            return (
                HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                Data(body.utf8)
            )
        }

        let result = try await client.transcribe(
            audioURL: audioURL,
            token: "session-token",
            idempotencyKey: "00000000-0000-4000-8000-000000000000"
        )

        XCTAssertFalse(result.videoUploaded)
        XCTAssertFalse(result.serverMediaRetained)
        XCTAssertTrue(result.hasAuthoritativeWalletSnapshot)
        XCTAssertEqual(
            result.wallet,
            PointsBalance(
                balance: 70,
                paidBalance: 50,
                promotionalBalance: 20,
                reversalDebt: 0,
                aiSpendableBalance: 50
            ))
    }

    func testLegacyTranscriptionResponseRefreshesTheAuthoritativeWallet() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let client = APIClient(baseURL: URL(string: "https://example.test")!, session: session)
        let audioURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("m4a")
        try Data("audio-only".utf8).write(to: audioURL)
        defer { try? FileManager.default.removeItem(at: audioURL) }
        var requestedPaths: [String] = []
        URLProtocolStub.handler = { request in
            requestedPaths.append(request.url?.path ?? "")
            if request.url?.path == "/videos/mobile-transcriptions" {
                let legacy =
                    #"{"request_id":"mobile-legacy","duration_seconds":2,"credits_charged":30,"balance":70,"video_uploaded":false,"server_media_retained":false,"cues":[]}"#
                return (
                    HTTPURLResponse(
                        url: request.url!,
                        statusCode: 200,
                        httpVersion: nil,
                        headerFields: nil
                    )!,
                    Data(legacy.utf8)
                )
            }
            XCTAssertEqual(request.url?.path, "/auth/points")
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "Authorization"),
                "Bearer session-token"
            )
            let wallet =
                #"{"balance":70,"paid_balance":40,"promotional_balance":30,"reversal_debt":0,"ai_spendable_balance":40}"#
            return (
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: nil
                )!,
                Data(wallet.utf8)
            )
        }

        let result = try await client.transcribe(
            audioURL: audioURL,
            token: "session-token",
            idempotencyKey: "00000000-0000-4000-8000-000000000000"
        )

        XCTAssertEqual(
            requestedPaths,
            ["/videos/mobile-transcriptions", "/auth/points"]
        )
        XCTAssertTrue(result.hasAuthoritativeWalletSnapshot)
        XCTAssertEqual(
            result.wallet,
            PointsBalance(
                balance: 70,
                paidBalance: 40,
                promotionalBalance: 30,
                reversalDebt: 0,
                aiSpendableBalance: 40
            ))
    }

    func testKnownTranscriptionErrorsHaveActionableGreekMessages() {
        let insufficientPaidCredits = APIError(
            status: 402,
            message: "Insufficient paid credits"
        )
        let insufficientCredits = APIError(status: 402, message: "Insufficient points")
        let reversal = APIError(status: 402, message: "Outstanding credit reversal")
        let inProgress = APIError(
            status: 409,
            message: "Transcription is already in progress"
        )
        let conflict = APIError(status: 409, message: "Idempotency key conflict")

        XCTAssertEqual(
            insufficientPaidCredits.errorDescription,
            APIError.insufficientPaidCreditsMessage
        )
        XCTAssertEqual(
            insufficientCredits.errorDescription,
            APIError.insufficientCreditsMessage
        )
        XCTAssertEqual(
            reversal.errorDescription,
            APIError.outstandingCreditReversalMessage
        )
        XCTAssertEqual(
            inProgress.errorDescription,
            APIError.transcriptionInProgressMessage
        )
        XCTAssertEqual(conflict.errorDescription, APIError.idempotencyConflictMessage)
        XCTAssertTrue(inProgress.errorDescription?.contains("Περίμενε") == true)
    }

    func testDeleteAccountUsesAuthenticatedDeleteEndpointAndIgnoresThe2xxBody() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let client = APIClient(baseURL: URL(string: "https://example.test")!, session: session)
        URLProtocolStub.handler = { request in
            XCTAssertEqual(request.url?.path, "/auth/me")
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "Authorization"),
                "Bearer session-token"
            )
            return (
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: nil
                )!,
                Data("not-json".utf8)
            )
        }

        try await client.deleteAccount(token: "session-token")
    }

    func testDeleteAccountDoesNotClaimSuccessForAFirstAttempt401Or404() async {
        for status in [401, 404] {
            let configuration = URLSessionConfiguration.ephemeral
            configuration.protocolClasses = [URLProtocolStub.self]
            let session = URLSession(configuration: configuration)
            let client = APIClient(baseURL: URL(string: "https://example.test")!, session: session)
            var requestCount = 0
            URLProtocolStub.handler = { request in
                requestCount += 1
                return (
                    HTTPURLResponse(
                        url: request.url!,
                        statusCode: status,
                        httpVersion: nil,
                        headerFields: nil
                    )!,
                    Data(#"{"detail":"Account state is unconfirmed"}"#.utf8)
                )
            }

            do {
                try await client.deleteAccount(token: "session-token")
                XCTFail("Expected AccountDeletionError for HTTP \(status)")
            } catch is AccountDeletionError {
                // Never present an invalid token/missing account as confirmed deletion.
            } catch {
                XCTFail("Unexpected error for HTTP \(status): \(error)")
            }
            XCTAssertEqual(requestCount, 1)
            session.invalidateAndCancel()
        }
    }

    func testDeleteAccountDoesNotClaimSuccessWhenRetryFindsA401Or404() async {
        for status in [401, 404] {
            let configuration = URLSessionConfiguration.ephemeral
            configuration.protocolClasses = [URLProtocolStub.self]
            let session = URLSession(configuration: configuration)
            let client = APIClient(baseURL: URL(string: "https://example.test")!, session: session)
            var requestCount = 0
            URLProtocolStub.handler = { request in
                requestCount += 1
                if requestCount == 1 {
                    throw URLError(.networkConnectionLost)
                }
                return (
                    HTTPURLResponse(
                        url: request.url!,
                        statusCode: status,
                        httpVersion: nil,
                        headerFields: nil
                    )!,
                    Data(#"{"detail":"Account state is unconfirmed"}"#.utf8)
                )
            }

            do {
                try await client.deleteAccount(token: "session-token")
                XCTFail("Expected AccountDeletionError for HTTP \(status)")
            } catch is AccountDeletionError {
                // The app clears local private state but reports unconfirmed deletion.
            } catch {
                XCTFail("Unexpected error for HTTP \(status): \(error)")
            }
            XCTAssertEqual(requestCount, 2)
            session.invalidateAndCancel()
        }
    }

    func testDeleteAccountDoesNotRetryOrHideAnExplicitServerRejection() async {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let client = APIClient(baseURL: URL(string: "https://example.test")!, session: session)
        var requestCount = 0
        URLProtocolStub.handler = { request in
            requestCount += 1
            return (
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 409,
                    httpVersion: nil,
                    headerFields: nil
                )!,
                Data(#"{"detail":"Deletion is blocked"}"#.utf8)
            )
        }

        do {
            try await client.deleteAccount(token: "session-token")
            XCTFail("Expected the explicit rejection")
        } catch let error as APIError {
            XCTAssertEqual(error.status, 409)
            XCTAssertEqual(error.message, "Deletion is blocked")
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
        XCTAssertEqual(requestCount, 1)
    }

    func testDeleteAccountReportsUncertaintyAfterTwoLostResponses() async {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let client = APIClient(baseURL: URL(string: "https://example.test")!, session: session)
        var requestCount = 0
        URLProtocolStub.handler = { _ in
            requestCount += 1
            throw URLError(.networkConnectionLost)
        }

        do {
            try await client.deleteAccount(token: "session-token")
            XCTFail("Expected an uncertain commit result")
        } catch is AccountDeletionError {
            // Expected: AppModel must now converge local privacy state.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
        XCTAssertEqual(requestCount, 2)
    }
}

private final class URLProtocolStub: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            guard let handler = Self.handler else { throw URLError(.badServerResponse) }
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
