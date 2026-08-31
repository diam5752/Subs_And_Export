import XCTest

extension GSubsUITests {
    func testOnlySelectedCueGetsAPositionOverride() throws {
        launch("--gsubs-ui-test-editor")

        XCTAssertTrue(app.otherElements["mobile-editor"].waitForExistence(timeout: 5))
        XCTAssertTrue(waitForHittable(app.buttons["cue-position-toggle-0"], timeout: 5))
        XCTAssertTrue(
            waitForValue(
                app.buttons["cue-position-toggle-0"],
                beginsWith: "Κοινή θέση",
                timeout: 2
            ))
        let globalPercentage = try XCTUnwrap(percentage(in: app.buttons["cue-position-toggle-0"]))
        app.buttons["cue-position-toggle-0"].tap()
        app.sliders["cue-position-slider-0"].adjust(toNormalizedSliderPosition: 0.82)
        XCTAssertTrue(
            waitForValue(
                app.buttons["cue-position-toggle-0"],
                beginsWith: "Δική του θέση",
                timeout: 2
            ))
        let firstCustomPercentage = try XCTUnwrap(
            percentage(in: app.buttons["cue-position-toggle-0"])
        )
        XCTAssertGreaterThan(firstCustomPercentage, globalPercentage + 20)
        XCTAssertTrue(
            waitForLabel(
                app.staticTexts["active-subtitle"],
                equals: "Τρέχων υπότιτλος: ΤΟ ΒΙΝΤΕΟ ΜΕΝΕΙ ΣΤΟ IPHONE",
                timeout: 2
            ))
        XCTAssertTrue(
            waitForValue(
                app.staticTexts["active-subtitle"],
                equals: "Θέση \(firstCustomPercentage)%",
                timeout: 2
            ))
        attachScreenshot(named: "Cue 1 custom position")

        app.buttons["cue-next"].tap()
        XCTAssertTrue(
            waitForValue(
                app.buttons["cue-position-toggle-1"],
                beginsWith: "Κοινή θέση",
                timeout: 2
            ))
        XCTAssertEqual(
            try XCTUnwrap(percentage(in: app.buttons["cue-position-toggle-1"])),
            globalPercentage
        )
        XCTAssertTrue(
            waitForLabel(
                app.staticTexts["active-subtitle"],
                equals: "Τρέχων υπότιτλος: ΟΙ ΥΠΟΤΙΤΛΟΙ ΕΡΧΟΝΤΑΙ ΕΤΟΙΜΟΙ",
                timeout: 2
            ))
        XCTAssertTrue(
            waitForValue(
                app.staticTexts["active-subtitle"],
                equals: "Θέση \(globalPercentage)%",
                timeout: 2
            ))

        app.buttons["cue-position-toggle-1"].tap()
        app.sliders["cue-position-slider-1"].adjust(toNormalizedSliderPosition: 0.52)
        let secondCustomPercentage = try XCTUnwrap(
            percentage(in: app.buttons["cue-position-toggle-1"])
        )
        XCTAssertNotEqual(secondCustomPercentage, firstCustomPercentage)

        app.buttons["cue-next"].tap()
        XCTAssertTrue(
            waitForValue(
                app.buttons["cue-position-toggle-2"],
                beginsWith: "Κοινή θέση",
                timeout: 2
            ))
        XCTAssertTrue(
            waitForLabel(
                app.staticTexts["active-subtitle"],
                equals: "Τρέχων υπότιτλος: ΤΟ EXPORT ΓΙΝΕΤΑΙ ΤΟΠΙΚΑ",
                timeout: 2
            ))
        XCTAssertTrue(
            waitForValue(
                app.staticTexts["active-subtitle"],
                equals: "Θέση \(globalPercentage)%",
                timeout: 2
            ))
        attachScreenshot(named: "Cue 3 global position")

        app.buttons["cue-previous"].tap()
        XCTAssertTrue(
            waitForValue(
                app.buttons["cue-position-toggle-1"],
                beginsWith: "Δική του θέση",
                timeout: 2
            ))
        XCTAssertEqual(
            try XCTUnwrap(percentage(in: app.buttons["cue-position-toggle-1"])),
            secondCustomPercentage
        )
        app.buttons["cue-previous"].tap()
        XCTAssertTrue(
            waitForValue(
                app.buttons["cue-position-toggle-0"],
                beginsWith: "Δική του θέση",
                timeout: 2
            ))
        XCTAssertEqual(
            try XCTUnwrap(percentage(in: app.buttons["cue-position-toggle-0"])),
            firstCustomPercentage
        )

        XCTAssertTrue(waitForHittable(app.buttons["cue-position-reset-0"], timeout: 2))
        app.buttons["cue-position-reset-0"].tap()
        XCTAssertTrue(
            waitForValue(
                app.buttons["cue-position-toggle-0"],
                beginsWith: "Κοινή θέση",
                timeout: 2
            ))
        app.buttons["cue-next"].tap()
        XCTAssertTrue(
            waitForValue(
                app.buttons["cue-position-toggle-1"],
                beginsWith: "Δική του θέση",
                timeout: 2
            ))
        XCTAssertEqual(
            try XCTUnwrap(percentage(in: app.buttons["cue-position-toggle-1"])),
            secondCustomPercentage
        )
    }

    func testSubtitleEditorFitsOnOneScreenAndKeyboard() {
        launch("--gsubs-ui-test-editor")

        let editor = app.descendants(matching: .any)["mobile-editor"]
        XCTAssertTrue(editor.waitForExistence(timeout: 3))
        XCTAssertFalse(app.scrollViews["studio-scroll"].exists)
        let preview = app.otherElements["video-preview"]
        let firstCue = app.descendants(matching: .any)["subtitle-cue-0"]
        let cuePosition = app.sliders["cue-position-slider-0"]
        let fontSize = app.buttons["font-size-increase"]
        let color = app.buttons["subtitle-color-white"]
        let globalPosition = app.sliders["global-position-slider"]
        let export = app.buttons["primary-action"]

        for element in [
            preview,
            firstCue,
            app.buttons["cue-next"],
            cuePosition,
            fontSize,
            color,
            globalPosition,
            export,
        ] {
            XCTAssertTrue(waitForHittable(element, timeout: 3), element.debugDescription)
        }
        XCTAssertLessThan(globalPosition.frame.maxY, export.frame.minY)
        let pointRoundingTolerance: CGFloat = 0.001
        for control in [
            app.buttons["cue-next"],
            app.buttons["cue-position-toggle-0"],
            fontSize,
            color,
        ] {
            XCTAssertGreaterThanOrEqual(control.frame.width + pointRoundingTolerance, 44)
            XCTAssertGreaterThanOrEqual(control.frame.height + pointRoundingTolerance, 44)
        }

        let previewY = preview.frame.minY
        let cueY = firstCue.frame.minY
        let exportY = export.frame.minY
        app.swipeUp()
        RunLoop.current.run(until: Date().addingTimeInterval(0.3))
        XCTAssertEqual(preview.frame.minY, previewY, accuracy: 1)
        XCTAssertEqual(firstCue.frame.minY, cueY, accuracy: 1)
        XCTAssertEqual(export.frame.minY, exportY, accuracy: 1)
        attachScreenshot(named: "One screen subtitle editor")

        firstCue.tap()
        firstCue.typeText(" QA")
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 2))
        XCTAssertTrue(preview.exists, preview.debugDescription)
        XCTAssertGreaterThan(preview.frame.width, 0)
        XCTAssertGreaterThan(preview.frame.height, 0)
        XCTAssertLessThanOrEqual(preview.frame.maxY, keyboard.frame.minY + 1)
        XCTAssertTrue(app.staticTexts["active-subtitle"].exists)
        for element in [firstCue, cuePosition, fontSize, color, globalPosition] {
            XCTAssertTrue(waitForHittable(element, timeout: 2), element.debugDescription)
            XCTAssertLessThanOrEqual(element.frame.maxY, keyboard.frame.minY + 1)
        }
        XCTAssertFalse(app.buttons["preview-playback-toggle"].exists)
        attachScreenshot(named: "One screen editor with keyboard")

        let keyboardNext = app.buttons["keyboard-cue-next"]
        XCTAssertTrue(waitForHittable(keyboardNext, timeout: 2))
        keyboardNext.tap()
        let secondCue = app.descendants(matching: .any)["subtitle-cue-1"]
        XCTAssertTrue(waitForHittable(secondCue, timeout: 2))
        secondCue.typeText(" NEXT")
        XCTAssertTrue((secondCue.value as? String)?.contains("NEXT") == true)
        XCTAssertTrue(waitForHittable(app.buttons["keyboard-cue-previous"], timeout: 2))
        app.buttons["keyboard-cue-previous"].tap()
        XCTAssertTrue(waitForHittable(firstCue, timeout: 2))
        firstCue.typeText(" BACK")
        XCTAssertTrue((firstCue.value as? String)?.contains("QA") == true)
        XCTAssertTrue((firstCue.value as? String)?.contains("BACK") == true)
        XCTAssertTrue(keyboard.exists)

        XCTAssertTrue(dismissKeyboardIfPresent())
        XCTAssertTrue(waitForHittable(export, timeout: 2))

        app.buttons["cue-next"].tap()
        XCTAssertTrue(waitForHittable(secondCue, timeout: 2))
        XCTAssertFalse(firstCue.exists)
        XCTAssertTrue(
            waitForLabel(
                app.staticTexts["active-subtitle"],
                contains: "NEXT",
                timeout: 2
            ))
        app.buttons["cue-previous"].tap()
        XCTAssertTrue(waitForHittable(firstCue, timeout: 2))
        XCTAssertTrue((firstCue.value as? String)?.contains("QA") == true)
        XCTAssertTrue((firstCue.value as? String)?.contains("BACK") == true)

        app.buttons["cue-counter"].tap()
        XCTAssertTrue(app.buttons["cue-picker-item-2"].waitForExistence(timeout: 2))
        app.buttons["cue-picker-item-2"].tap()
        XCTAssertTrue(
            waitForHittable(
                app.descendants(matching: .any)["subtitle-cue-2"],
                timeout: 2
            ))
    }

    func testLandscapeKeyboardKeepsEveryEditorControlVisible() {
        launch("--gsubs-ui-test-editor")
        XCUIDevice.shared.orientation = .landscapeLeft

        let cue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(cue, timeout: 3))
        XCTAssertGreaterThan(app.frame.width, app.frame.height)
        for element in [
            app.otherElements["video-preview"],
            app.buttons["close-video"],
            app.buttons["account-menu"],
            app.buttons["cue-next"],
            app.sliders["cue-position-slider-0"],
            app.buttons["font-size-increase"],
            app.buttons["subtitle-color-white"],
            app.sliders["global-position-slider"],
        ] {
            XCTAssertTrue(waitForHittable(element, timeout: 2), element.debugDescription)
        }
        attachScreenshot(named: "Landscape editor without keyboard")

        cue.tap()
        cue.typeText(" QA")
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 2))
        let compactPreview = app.otherElements["video-preview"]
        XCTAssertTrue(compactPreview.exists, compactPreview.debugDescription)
        XCTAssertGreaterThan(compactPreview.frame.width, 0)
        XCTAssertGreaterThan(compactPreview.frame.height, 0)
        XCTAssertLessThanOrEqual(compactPreview.frame.maxY, keyboard.frame.minY + 1)
        for element in [
            cue,
            app.sliders["cue-position-slider-0"],
            app.buttons["font-size-increase"],
            app.buttons["subtitle-color-white"],
            app.sliders["global-position-slider"],
        ] {
            XCTAssertTrue(waitForHittable(element, timeout: 2), element.debugDescription)
            XCTAssertLessThanOrEqual(element.frame.maxY, keyboard.frame.minY + 1)
        }
        XCTAssertFalse(app.buttons["preview-playback-toggle"].exists)
        attachScreenshot(named: "Landscape editor with keyboard")
        XCTAssertTrue(dismissKeyboardIfPresent())
        XCTAssertTrue(waitForHittable(app.buttons["close-video"], timeout: 2))
        let accountMenu = app.buttons["account-menu"]
        XCTAssertTrue(accountMenu.waitForExistence(timeout: 2), accountMenu.debugDescription)
        XCTAssertTrue(waitForStableFrame(accountMenu, timeout: 3), accountMenu.debugDescription)
        accountMenu.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(app.buttons["Απόρρητο"].waitForExistence(timeout: 2))
    }

    func testLandscapeExportShowsSaveAndShareActions() {
        launch("--gsubs-ui-test-slow-export")
        XCUIDevice.shared.orientation = .landscapeLeft

        let export = app.descendants(matching: .any)["primary-action"]
        XCTAssertTrue(
            waitForEnabledAndHittable(export, timeout: 3),
            export.debugDescription
        )
        export.tap()
        XCTAssertTrue(app.staticTexts["Έτοιμο"].waitForExistence(timeout: 12))
        XCTAssertTrue(waitForHittable(app.buttons["save-to-photos"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["share-export"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["close-video"], timeout: 2))
        XCTAssertTrue(waitForHittable(app.buttons["account-menu"], timeout: 2))
        attachScreenshot(named: "Landscape export actions")
    }

    func testAccessibilityMaximumEditorFitsWithoutScrolling() {
        launch("--gsubs-ui-test-editor")
        let defaultCue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(defaultCue, timeout: 3))
        let defaultCueHeight = defaultCue.frame.height
        app.terminate()

        launch(
            "--gsubs-ui-test-editor",
            contentSizeCategory: "UICTContentSizeCategoryAccessibilityXXXL"
        )

        XCTAssertTrue(app.descendants(matching: .any)["mobile-editor"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.scrollViews["studio-scroll"].exists)
        let export = app.buttons["primary-action"]
        let preview = app.otherElements["video-preview"]
        let cue = app.descendants(matching: .any)["subtitle-cue-0"]
        let cueMode = app.buttons["cue-position-toggle-0"]
        let fontSize = app.buttons["font-size-increase"]
        let color = app.buttons["subtitle-color-white"]
        let globalPosition = app.sliders["global-position-slider"]
        for element in [
            preview,
            cue,
            app.sliders["cue-position-slider-0"],
            cueMode,
            fontSize,
            color,
            globalPosition,
            export,
        ] {
            XCTAssertTrue(waitForHittable(element, timeout: 3), element.debugDescription)
        }
        let accessibilityCueHeight = cue.frame.height
        XCTAssertGreaterThan(cue.frame.height, defaultCueHeight + 8)
        assertVerticallyOrderedAndContained([
            preview,
            cue,
            cueMode,
            fontSize,
            color,
            globalPosition,
            export,
        ])
        attachScreenshot(named: "Accessibility maximum one screen editor")

        cue.tap()
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 3))
        XCTAssertTrue(waitForStableFrame(keyboard, timeout: 2))
        let focusedCue = app.descendants(matching: .any)["subtitle-cue-0"]
        XCTAssertTrue(waitForHittable(focusedCue, timeout: 2))
        focusedCue.typeText(" QA")
        XCTAssertEqual(focusedCue.frame.height, accessibilityCueHeight, accuracy: 1)
        XCTAssertTrue(preview.exists, preview.debugDescription)
        XCTAssertGreaterThan(preview.frame.width, 0)
        XCTAssertGreaterThan(preview.frame.height, 0)
        XCTAssertLessThanOrEqual(preview.frame.maxY, keyboard.frame.minY + 1)
        for element in [
            focusedCue,
            app.sliders["cue-position-slider-0"],
            app.buttons["font-size-increase"],
            app.buttons["subtitle-color-white"],
            app.sliders["global-position-slider"],
        ] {
            XCTAssertTrue(waitForHittable(element, timeout: 2), element.debugDescription)
            XCTAssertLessThanOrEqual(element.frame.maxY, keyboard.frame.minY + 1)
        }
        assertVerticallyOrderedAndContained([
            preview,
            focusedCue,
            cueMode,
            fontSize,
            color,
            globalPosition,
        ])
        XCTAssertFalse(app.buttons["preview-playback-toggle"].exists)
        attachScreenshot(named: "Accessibility maximum editor with keyboard")
        XCTAssertTrue(dismissKeyboardIfPresent())
    }
}
