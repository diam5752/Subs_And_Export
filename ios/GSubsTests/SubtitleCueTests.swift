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
        let json = Data(
            #"{"request_id":"mobile-1","duration_seconds":2.0,"credits_charged":30,"balance":70,"paid_balance":50,"promotional_balance":20,"reversal_debt":0,"ai_spendable_balance":50,"video_uploaded":false,"server_media_retained":false,"cues":[{"start":0,"end":2,"text":"ΓΕΙΑ","words":[]}]}"#
                .utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let result = try decoder.decode(MobileTranscriptionResult.self, from: json)

        XCTAssertEqual(result.requestId, "mobile-1")
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
        XCTAssertFalse(result.videoUploaded)
        XCTAssertFalse(result.serverMediaRetained)
        XCTAssertEqual(result.cues.first?.text, "ΓΕΙΑ")
    }

    func testLegacyMobileResponseDecodesButRequiresAnAuthoritativeWalletRefresh() throws {
        let json = Data(
            #"{"request_id":"mobile-legacy","duration_seconds":2.0,"credits_charged":30,"balance":70,"video_uploaded":false,"server_media_retained":false,"cues":[]}"#
                .utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let result = try decoder.decode(MobileTranscriptionResult.self, from: json)

        XCTAssertFalse(result.hasAuthoritativeWalletSnapshot)
        XCTAssertEqual(result.balance, 70)
        XCTAssertEqual(result.paidBalance, 70)
        XCTAssertEqual(result.aiSpendableBalance, 70)
    }

    func testStyleFallsBackToGlobalPositionAndKeepsOverrideAcrossTextEdits() {
        var style = SubtitleStyle()
        style.bottomOffset = 0.2
        var cue = SubtitleCue(start: 0, end: 1, text: "ΑΡΧΙΚΟ", words: [])

        XCTAssertNil(cue.bottomOffsetOverride)
        XCTAssertEqual(style.resolvedBottomOffset(for: cue), 0.2, accuracy: 0.000_1)

        cue.bottomOffsetOverride = 0.48
        cue.text = "ΔΙΟΡΘΩΜΕΝΟ ΚΕΙΜΕΝΟ"

        XCTAssertEqual(cue.bottomOffsetOverride, 0.48)
        XCTAssertEqual(style.resolvedBottomOffset(for: cue), 0.48, accuracy: 0.000_1)

        cue.bottomOffsetOverride = nil

        XCTAssertEqual(style.resolvedBottomOffset(for: cue), 0.2, accuracy: 0.000_1)
    }

    func testLegacyCueJSONDecodesWithoutPositionOverride() throws {
        let legacyJSON = Data(
            #"{"start":0.0,"end":1.5,"text":"ΠΑΛΙΟ PROJECT","words":[]}"#.utf8
        )

        let cue = try JSONDecoder().decode(SubtitleCue.self, from: legacyJSON)

        XCTAssertEqual(cue.text, "ΠΑΛΙΟ PROJECT")
        XCTAssertNil(cue.bottomOffsetOverride)
        XCTAssertEqual(SubtitleStyle().resolvedBottomOffset(for: cue), 0.12, accuracy: 0.000_1)
    }

    func testCueIdentityIsUniqueForDuplicateTimingsAndSurvivesLocalRoundTrip() throws {
        var first = SubtitleCue(start: 0, end: 1, text: "ΠΡΩΤΟ", words: [])
        let second = SubtitleCue(start: 0, end: 1, text: "ΔΕΥΤΕΡΟ", words: [])

        XCTAssertNotEqual(first.id, second.id)
        let originalID = first.id
        first.text = "ΑΛΛΑΓΜΕΝΟ"
        first.bottomOffsetOverride = 0.4

        let decoded = try JSONDecoder().decode(
            SubtitleCue.self,
            from: JSONEncoder().encode(first)
        )

        XCTAssertEqual(first.id, originalID)
        XCTAssertEqual(decoded.id, originalID)
        XCTAssertEqual(decoded.bottomOffsetOverride, 0.4)
    }

    func testSharedSubtitleLayoutNormalizesAndScalesPreviewAndExportMetrics() {
        XCTAssertEqual(SubtitleLayout.normalizedText(" \n  γεια σου \n"), "ΓΕΙΑ ΣΟΥ")

        for width in [CGFloat(247), CGFloat(1_080)] {
            XCTAssertEqual(
                SubtitleLayout.maximumTextWidth(frameWidth: width) / width,
                SubtitleLayout.maximumTextWidthFraction,
                accuracy: 0.000_1
            )
            XCTAssertEqual(
                SubtitleLayout.verticalPadding(frameWidth: width) / width,
                SubtitleLayout.verticalPaddingFraction,
                accuracy: 0.000_1
            )
            for scale in [0.75, 1.0, 1.35] {
                XCTAssertEqual(
                    SubtitleLayout.baseFontSize(frameWidth: width, scale: scale) / width,
                    SubtitleLayout.fontSizeFraction * CGFloat(scale),
                    accuracy: 0.000_1
                )
            }
        }

        let multiline = "ΑΥΤΟΣ ΕΙΝΑΙ ΕΝΑΣ ΠΟΛΥ ΜΕΓΑΛΟΣ ΥΠΟΤΙΤΛΟΣ ΠΟΥ ΧΡΕΙΑΖΕΤΑΙ ΤΡΕΙΣ ΓΡΑΜΜΕΣ ΚΕΙΜΕΝΟΥ"
        let previewFontSize = SubtitleLayout.resolvedFontSize(
            text: multiline,
            frameWidth: 247,
            scale: 1
        )
        let exportFontSize = SubtitleLayout.resolvedFontSize(
            text: multiline,
            frameWidth: 1_080,
            scale: 1
        )
        XCTAssertEqual(previewFontSize / 247, exportFontSize / 1_080, accuracy: 0.000_1)
    }

    func testTimelineFindsUnsortedCuesAndRespectsGaps() {
        let late = SubtitleCue(start: 3, end: 4, text: "ΔΕΥΤΕΡΟ", words: [])
        let early = SubtitleCue(start: 0, end: 1, text: "ΠΡΩΤΟ", words: [])
        let timeline = SubtitleTimeline(cues: [late, early])

        XCTAssertEqual(timeline.activeCue(at: 0)?.text, "ΠΡΩΤΟ")
        XCTAssertNil(timeline.activeCue(at: 1))
        XCTAssertNil(timeline.activeCue(at: 2.9))
        XCTAssertEqual(timeline.activeCue(at: 3.5)?.text, "ΔΕΥΤΕΡΟ")
        XCTAssertNil(timeline.activeCue(at: 4))
    }

    func testTimelinePollingChangesOnlyAtCueBoundaries() {
        let timeline = SubtitleTimeline(cues: [
            SubtitleCue(start: 0, end: 1, text: "Α", words: []),
            SubtitleCue(start: 1, end: 2, text: "Β", words: []),
        ])
        let sampledIDs = stride(from: 0.0, through: 2.4, by: 0.1)
            .map { timeline.activeCue(at: $0)?.id }
        let transitions = zip(sampledIDs, sampledIDs.dropFirst())
            .filter { $0.0 != $0.1 }

        XCTAssertEqual(transitions.count, 2)
    }
}
