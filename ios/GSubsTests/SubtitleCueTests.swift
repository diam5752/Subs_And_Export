import XCTest
@testable import GSubs

final class SubtitleCueTests: XCTestCase {
    func testCueUsesHalfOpenTimelineBoundary() {
        let cue = SubtitleCue(start: 1, end: 2, text: "ΓΕΙΑ", words: [])

        XCTAssertFalse(cue.contains(0.999))
        XCTAssertTrue(cue.contains(1))
        XCTAssertTrue(cue.contains(1.999))
        XCTAssertFalse(cue.contains(2))
    }

    func testMobileResponseDecodesSnakeCaseContract() throws {
        let json = Data(#"{"request_id":"mobile-1","duration_seconds":2.0,"credits_charged":30,"balance":70,"video_uploaded":false,"server_media_retained":false,"cues":[{"start":0,"end":2,"text":"ΓΕΙΑ","words":[]}]}"#.utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let result = try decoder.decode(MobileTranscriptionResult.self, from: json)

        XCTAssertEqual(result.requestId, "mobile-1")
        XCTAssertFalse(result.videoUploaded)
        XCTAssertFalse(result.serverMediaRetained)
        XCTAssertEqual(result.cues.first?.text, "ΓΕΙΑ")
    }
}
