import XCTest

extension GSubsUITests {
    func testLocalTranscriptionEditingStylingExportSaveAndShare() {
        launch("--gsubs-ui-test-ready")
        XCTAssertTrue(app.buttons["Υπότιτλοι · 30 credits"].waitForExistence(timeout: 3))

        app.buttons["preview-playback-toggle"].tap()
        XCTAssertTrue(app.buttons["Παύση"].waitForExistence(timeout: 2))
        app.buttons["preview-playback-toggle"].tap()
        XCTAssertTrue(app.buttons["Αναπαραγωγή"].waitForExistence(timeout: 2))

        app.buttons["Υπότιτλοι · 30 credits"].tap()
        XCTAssertTrue(app.buttons["Εξαγωγή MP4"].waitForExistence(timeout: 5))
        XCTAssertTrue(
            waitForLabel(
                app.staticTexts["active-subtitle"],
                contains: "ΤΟ ΒΙΝΤΕΟ ΜΕΝΕΙ ΣΤΟ IPHONE",
                timeout: 2
            ))

        let firstCue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(firstCue, timeout: 2))
        firstCue.tap()
        firstCue.typeText(" QA")
        XCTAssertTrue(dismissKeyboardIfPresent())

        for identifier in ["subtitle-color-white", "subtitle-color-cyan", "subtitle-color-yellow"] {
            XCTAssertTrue(waitForHittable(app.buttons[identifier], timeout: 2))
            app.buttons[identifier].tap()
        }
        app.buttons["font-size-increase"].tap()
        app.buttons["font-size-decrease"].tap()
        app.sliders["cue-position-slider-0"].adjust(toNormalizedSliderPosition: 0.48)
        app.sliders["global-position-slider"].adjust(toNormalizedSliderPosition: 0.35)

        let export = app.buttons["primary-action"]
        XCTAssertFalse(app.staticTexts["Έτοιμο"].exists)
        XCTAssertTrue(waitForEnabledAndHittable(export, timeout: 3))
        export.tap()
        XCTAssertTrue(app.staticTexts["Έτοιμο"].waitForExistence(timeout: 12))
        XCTAssertTrue(waitForHittable(app.buttons["save-to-photos"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["share-export"], timeout: 2))

        allowPhotoWriteIfPrompted {
            app.buttons["save-to-photos"].tap()
        }
        XCTAssertTrue(
            waitAndReveal(
                app.staticTexts["Αποθηκεύτηκε στις Φωτογραφίες."],
                timeout: 5
            ))

        let shareButton = app.buttons["share-export"]
        XCTAssertTrue(waitForHittable(shareButton, timeout: 3))
        shareButton.tap()
        let activityList = app.descendants(matching: .any)["ActivityListView"]
        let closeCandidates = [
            app.buttons["Close"],
            app.buttons["Cancel"],
            app.buttons["Κλείσιμο"],
            app.buttons["Ακύρωση"],
        ]
        XCTAssertTrue(
            waitForShareSurface(
                activityList: activityList,
                obscuredButton: shareButton,
                closeCandidates: closeCandidates,
                timeout: 3
            ))
    }

    func testNewVideoStartsWithThePicker() {
        launch("--gsubs-ui-test-ready")

        XCTAssertTrue(revealUp(app.buttons["account-menu"]))
        app.buttons["account-menu"].tap()
        app.buttons["Νέο βίντεο"].tap()
        XCTAssertTrue(app.buttons["video-picker"].waitForExistence(timeout: 3))
    }

    func testExportFailureIsVisibleAndRetryableWithoutCoveringPreview() {
        launch("--gsubs-ui-test-export-failure")

        let export = app.buttons["primary-action"]
        XCTAssertTrue(waitForEnabledAndHittable(export, timeout: 3))
        export.tap()

        let status = app.descendants(matching: .any)["editor-status"]
        XCTAssertTrue(status.waitForExistence(timeout: 4))
        XCTAssertTrue(
            waitForLabel(
                status,
                contains: "Η τοπική εξαγωγή δεν ολοκληρώθηκε.",
                timeout: 2
            ))
        let retryExport = app.buttons["primary-action"]
        XCTAssertTrue(
            waitForEnabledAndHittable(retryExport, timeout: 5),
            retryExport.debugDescription
        )
        XCTAssertLessThanOrEqual(app.otherElements["video-preview"].frame.maxY, status.frame.minY)
        XCTAssertLessThan(status.frame.maxY, retryExport.frame.minY)
        XCTAssertFalse(app.staticTexts["Έτοιμο"].exists)
        attachScreenshot(named: "Visible local export failure")
    }

    func testEditingControlsFreezeWhileExporting() {
        launch("--gsubs-ui-test-held-export")

        let cue = app.descendants(matching: .any)["subtitle-cue-0"]
        let controls = [
            cue,
            app.buttons["cue-next"],
            app.sliders["cue-position-slider-0"],
            app.buttons["cue-position-toggle-0"],
            app.buttons["font-size-increase"],
            app.buttons["subtitle-color-white"],
            app.sliders["global-position-slider"],
        ]
        for control in controls {
            XCTAssertTrue(waitForHittable(control, timeout: 3), control.debugDescription)
        }
        let activeSubtitle = app.staticTexts["active-subtitle"]
        XCTAssertTrue(activeSubtitle.waitForExistence(timeout: 3))
        let playback = app.buttons["preview-playback-toggle"]
        XCTAssertTrue(waitForHittable(playback, timeout: 2))
        playback.tap()
        XCTAssertTrue(waitForLabel(playback, equals: "Παύση", timeout: 2))
        let originalText = cue.value as? String

        let export = app.buttons["primary-action"]
        XCTAssertTrue(waitForEnabledAndHittable(export, timeout: 2))
        export.tap()
        XCTAssertTrue(waitForDisabled(export, timeout: 2))
        XCTAssertTrue(waitForAllDisabled(controls + [playback], timeout: 2))
        XCTAssertTrue(waitForLabel(playback, equals: "Αναπαραγωγή", timeout: 2))
        let frozenPreviewLabel = activeSubtitle.label
        let frozenPreviewValue = activeSubtitle.value as? String
        RunLoop.current.run(until: Date().addingTimeInterval(1.6))
        XCTAssertEqual(cue.value as? String, originalText)
        XCTAssertEqual(activeSubtitle.label, frozenPreviewLabel)
        XCTAssertEqual(activeSubtitle.value as? String, frozenPreviewValue)
        XCTAssertEqual(playback.label, "Αναπαραγωγή")
        attachScreenshot(named: "Editor frozen during local export")
    }

    func testTranscriptionFailureCanRetryAndProjectCanClose() {
        launch("--gsubs-ui-test-transcription-failure")
        app.buttons["primary-action"].tap()

        XCTAssertTrue(
            app.staticTexts[
                "Η μεταγραφή δεν είναι προσωρινά διαθέσιμη."
            ].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["primary-action"].isEnabled)
        app.buttons["close-video"].tap()
        XCTAssertTrue(app.buttons["video-picker"].waitForExistence(timeout: 2))
    }
}
