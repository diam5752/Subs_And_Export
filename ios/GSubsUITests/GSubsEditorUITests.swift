import XCTest

extension GSubsUITests {
    func testImmersiveEditorShowsOnlyCanvasAndSwipeHandle() {
        let cue = launchEditorAndWaitForCue()
        pauseImmersivePlaybackIfNeeded()

        let preview = app.otherElements["video-preview"]
        let handle = app.buttons["immersive-tools-handle"]
        XCTAssertTrue(waitForHittable(preview, timeout: 3), preview.debugDescription)
        XCTAssertTrue(waitForHittable(cue, timeout: 3), cue.debugDescription)
        XCTAssertTrue(waitForHittable(handle, timeout: 3), handle.debugDescription)
        XCTAssertFalse(app.buttons["account-menu"].exists)
        XCTAssertFalse(app.buttons["close-video"].exists)
        XCTAssertFalse(app.buttons["primary-action"].exists)
        XCTAssertFalse(app.buttons["cue-next"].exists)
        XCTAssertFalse(app.scrollViews["studio-scroll"].exists)
        XCTAssertEqual(app.statusBars.count, 0)

        let appFrame = app.frame
        XCTAssertLessThanOrEqual(preview.frame.minY, appFrame.minY + 1)
        XCTAssertGreaterThanOrEqual(preview.frame.maxY, appFrame.maxY - 1)
        XCTAssertLessThanOrEqual(preview.frame.minX, appFrame.minX + 1)
        XCTAssertGreaterThanOrEqual(preview.frame.maxX, appFrame.maxX - 1)
        attachScreenshot(named: "Immersive video canvas")

        handle.tap()

        let drawer = app.descendants(matching: .any)["immersive-tools-drawer"]
        XCTAssertTrue(drawer.waitForExistence(timeout: 3), drawer.debugDescription)
        XCTAssertTrue(waitForHittable(app.buttons["account-menu"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["close-video"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["primary-action"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["cue-next"], timeout: 2))
        attachScreenshot(named: "Swipe-down tools drawer")

        closeImmersiveTools()
        XCTAssertTrue(waitForHittable(cue, timeout: 2))
        XCTAssertFalse(app.buttons["account-menu"].exists)
    }

    func testOnlySelectedCueGetsAPositionOverride() throws {
        let firstCue = launchEditorAndWaitForCue()
        pauseImmersivePlaybackIfNeeded()

        let initialPercentage = try XCTUnwrap(positionPercentage(of: firstCue))
        let start = firstCue.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        let end = start.withOffset(CGVector(dx: 0, dy: -180))
        start.press(forDuration: 0.08, thenDragTo: end)

        XCTAssertTrue(
            waitForValue(firstCue, contains: "θέση", timeout: 2),
            firstCue.debugDescription
        )
        let firstCustomPercentage = try XCTUnwrap(positionPercentage(of: firstCue))
        XCTAssertGreaterThan(firstCustomPercentage, initialPercentage + 10)
        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 0.5))
        attachScreenshot(named: "Direct cue drag")

        openImmersiveTools()
        app.buttons["cue-next"].tap()
        closeImmersiveTools()

        let secondCue = app.descendants(matching: .any)["subtitle-cue-1"]
        XCTAssertTrue(waitForHittable(secondCue, timeout: 3), secondCue.debugDescription)
        XCTAssertEqual(try XCTUnwrap(positionPercentage(of: secondCue)), initialPercentage)

        openImmersiveTools()
        app.buttons["cue-previous"].tap()
        closeImmersiveTools()
        XCTAssertTrue(waitForHittable(firstCue, timeout: 3), firstCue.debugDescription)
        XCTAssertEqual(try XCTUnwrap(positionPercentage(of: firstCue)), firstCustomPercentage)

        openImmersiveTools()
        let reset = app.buttons["current-cue-position-reset"]
        XCTAssertTrue(waitForHittable(reset, timeout: 2), reset.debugDescription)
        reset.tap()
        closeImmersiveTools()
        XCTAssertEqual(try XCTUnwrap(positionPercentage(of: firstCue)), initialPercentage)
    }

    func testSubtitleEditorFitsOnOneScreenAndKeyboard() {
        let firstCue = launchEditorAndWaitForCue()
        pauseImmersivePlaybackIfNeeded()

        let preview = app.otherElements["video-preview"]
        XCTAssertTrue(waitForHittable(firstCue, timeout: 3), firstCue.debugDescription)
        XCTAssertTrue(waitForHittable(preview, timeout: 3), preview.debugDescription)
        XCTAssertFalse(app.scrollViews["studio-scroll"].exists)

        firstCue.tap()
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 3), keyboard.debugDescription)
        let focusedFirstCue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(focusedFirstCue, timeout: 2), focusedFirstCue.debugDescription)
        focusedFirstCue.typeText(" QA")
        XCTAssertTrue(waitForValue(focusedFirstCue, contains: "QA", timeout: 3))
        XCTAssertTrue(preview.exists, preview.debugDescription)
        XCTAssertLessThanOrEqual(preview.frame.maxY, keyboard.frame.minY + 1)
        XCTAssertFalse(app.buttons["account-menu"].exists)
        XCTAssertFalse(app.buttons["primary-action"].exists)
        attachScreenshot(named: "Direct on-video text editing")

        let keyboardNext = app.buttons["keyboard-cue-next"]
        XCTAssertTrue(waitForHittable(keyboardNext, timeout: 8), keyboardNext.debugDescription)
        keyboardNext.tap()
        let secondCue = app.descendants(matching: .any)["subtitle-cue-1"]
        XCTAssertTrue(waitForHittable(secondCue, timeout: 5), secondCue.debugDescription)
        secondCue.typeText(" NEXT")
        XCTAssertTrue(waitForValue(secondCue, contains: "NEXT", timeout: 5))

        XCTAssertTrue(waitForHittable(app.buttons["keyboard-cue-previous"], timeout: 5))
        app.buttons["keyboard-cue-previous"].tap()
        XCTAssertTrue(waitForHittable(focusedFirstCue, timeout: 5), focusedFirstCue.debugDescription)
        XCTAssertTrue(waitForValue(focusedFirstCue, contains: "QA", timeout: 5))
        XCTAssertTrue(dismissKeyboardIfPresent())
        XCTAssertTrue(waitForHittable(app.buttons["immersive-tools-handle"], timeout: 3))
    }

    func testLandscapeKeyboardKeepsEveryEditorControlVisible() {
        launch("--gsubs-ui-test-editor")
        XCUIDevice.shared.orientation = .landscapeLeft

        let cue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(cue, timeout: 4), cue.debugDescription)
        pauseImmersivePlaybackIfNeeded()
        XCTAssertGreaterThan(app.frame.width, app.frame.height)
        XCTAssertFalse(app.buttons["account-menu"].exists)
        XCTAssertTrue(waitForHittable(app.buttons["immersive-tools-handle"], timeout: 2))

        cue.tap()
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 3), keyboard.debugDescription)
        let focusedCue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(focusedCue, timeout: 3), focusedCue.debugDescription)
        focusedCue.typeText(" QA")
        let preview = app.otherElements["video-preview"]
        XCTAssertTrue(preview.exists, preview.debugDescription)
        XCTAssertGreaterThan(preview.frame.width, 0)
        XCTAssertGreaterThan(preview.frame.height, 0)
        XCTAssertLessThanOrEqual(preview.frame.maxY, keyboard.frame.minY + 1)
        attachScreenshot(named: "Landscape direct edit")

        XCTAssertTrue(dismissKeyboardIfPresent())
        openImmersiveTools()
        XCTAssertTrue(waitForHittable(app.buttons["close-video"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["account-menu"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["font-size-increase"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["subtitle-color-white"], timeout: 2))
    }

    func testLandscapeExportShowsSaveAndShareActions() {
        launch("--gsubs-ui-test-slow-export")
        XCUIDevice.shared.orientation = .landscapeLeft
        openImmersiveTools(timeout: 4)

        let export = app.buttons["primary-action"]
        XCTAssertTrue(waitForEnabledAndHittable(export, timeout: 3), export.debugDescription)
        export.tap()
        XCTAssertTrue(app.staticTexts["Έτοιμο"].waitForExistence(timeout: 12))
        XCTAssertTrue(waitForHittable(app.buttons["save-to-photos"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["share-export"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["close-video"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["account-menu"], timeout: 2))
        attachScreenshot(named: "Landscape export actions")
    }

    func testAccessibilityMaximumEditorFitsWithoutScrolling() {
        let cue = launchEditorAndWaitForCue(
            contentSizeCategory: "UICTContentSizeCategoryAccessibilityXXXL"
        )
        pauseImmersivePlaybackIfNeeded()

        let preview = app.otherElements["video-preview"]
        let handle = app.buttons["immersive-tools-handle"]
        XCTAssertTrue(waitForHittable(preview, timeout: 3), preview.debugDescription)
        XCTAssertTrue(waitForHittable(cue, timeout: 3), cue.debugDescription)
        XCTAssertTrue(waitForHittable(handle, timeout: 3), handle.debugDescription)
        XCTAssertGreaterThanOrEqual(handle.frame.width, 44)
        XCTAssertGreaterThanOrEqual(handle.frame.height, 44)
        XCTAssertTrue((cue.value as? String)?.contains("θέση 12%") == true)
        XCTAssertFalse(app.scrollViews["studio-scroll"].exists)
        attachScreenshot(named: "Accessibility immersive canvas")

        cue.tap()
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 3), keyboard.debugDescription)
        let focusedCue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(focusedCue, timeout: 3), focusedCue.debugDescription)
        focusedCue.typeText(" QA")
        XCTAssertTrue(waitForValue(focusedCue, contains: "QA", timeout: 3))
        XCTAssertLessThanOrEqual(preview.frame.maxY, keyboard.frame.minY + 1)
        attachScreenshot(named: "Accessibility direct edit")
        XCTAssertTrue(dismissKeyboardIfPresent())

        openImmersiveTools()
        XCTAssertTrue(waitForHittable(app.buttons["font-size-increase"], timeout: 3))
        XCTAssertTrue(waitForHittable(app.buttons["subtitle-color-white"], timeout: 3))
        XCTAssertTrue(waitForHittable(app.buttons["primary-action"], timeout: 3))
    }
}
