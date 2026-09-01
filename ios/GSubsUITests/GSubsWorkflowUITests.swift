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
        let firstCue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(firstCue, timeout: 5))
        pauseImmersivePlaybackIfNeeded()
        firstCue.tap()
        firstCue.typeText(" QA")
        XCTAssertTrue(dismissKeyboardIfPresent())

        openImmersiveTools()
        for identifier in ["subtitle-color-white", "subtitle-color-cyan", "subtitle-color-yellow"] {
            XCTAssertTrue(waitForHittable(app.buttons[identifier], timeout: 2))
            app.buttons[identifier].tap()
        }
        app.buttons["font-size-increase"].tap()
        app.buttons["font-size-decrease"].tap()
        closeImmersiveTools()

        let dragStart = firstCue.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        dragStart.press(
            forDuration: 0.08,
            thenDragTo: dragStart.withOffset(CGVector(dx: 0, dy: -130))
        )
        XCTAssertTrue((positionPercentage(of: firstCue) ?? 0) > 12)

        openImmersiveTools()
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
        openImmersiveTools()

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
        XCTAssertLessThan(status.frame.maxY, retryExport.frame.minY)
        XCTAssertTrue(app.otherElements["video-preview"].exists)
        XCTAssertFalse(app.staticTexts["Έτοιμο"].exists)
        attachScreenshot(named: "Visible local export failure")
    }

    func testEditingControlsFreezeWhileExporting() {
        launch("--gsubs-ui-test-held-export")
        openImmersiveTools()

        let cue = app.descendants(matching: .any)["subtitle-cue-0"]
        let controls = [
            app.buttons["cue-next"],
            app.buttons["font-size-increase"],
            app.buttons["subtitle-color-white"],
            app.buttons["close-video"],
            app.buttons["account-menu"],
        ]
        for control in controls {
            XCTAssertTrue(waitForHittable(control, timeout: 3), control.debugDescription)
        }
        let playback = app.buttons["preview-playback-toggle"]
        XCTAssertTrue(playback.waitForExistence(timeout: 2))
        let originalText = cue.value as? String

        let export = app.buttons["primary-action"]
        XCTAssertTrue(waitForEnabledAndHittable(export, timeout: 2))
        export.tap()
        XCTAssertTrue(waitForDisabled(export, timeout: 2))
        XCTAssertTrue(waitForAllDisabled(controls, timeout: 2))
        XCTAssertFalse(playback.isEnabled)
        XCTAssertTrue(waitForLabel(playback, equals: "Αναπαραγωγή", timeout: 2))
        RunLoop.current.run(until: Date().addingTimeInterval(1.6))
        XCTAssertEqual(cue.value as? String, originalText)
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
