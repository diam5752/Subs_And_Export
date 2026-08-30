import Foundation
import XCTest
@testable import GSubs

final class APIClientTests: XCTestCase {
    override func tearDown() {
        URLProtocolStub.handler = nil
        super.tearDown()
    }

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
            let body = #"{"request_id":"mobile-1","duration_seconds":2,"credits_charged":30,"balance":70,"video_uploaded":false,"server_media_retained":false,"cues":[]}"#
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
        }

        let result = try await client.transcribe(
            audioURL: audioURL,
            token: "session-token",
            idempotencyKey: "00000000-0000-4000-8000-000000000000"
        )

        XCTAssertFalse(result.videoUploaded)
        XCTAssertFalse(result.serverMediaRetained)
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
