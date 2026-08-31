import XCTest

extension GSubsUITests {
    func testLoginRegistrationPrivacyAndSignOut() {
        launch("--gsubs-ui-test-unauthenticated")

        XCTAssertTrue(app.otherElements["gsubs beta"].waitForExistence(timeout: 3))
        openAndClosePrivacy()

        app.buttons["Εγγραφή"].tap()
        type("iOS QA", into: app.textFields["Όνομα"])
        app.typeText("\n")
        type("ios-qa@gsubs.local", into: app.textFields["Ηλεκτρονική διεύθυνση"])
        app.typeText("\n")
        XCTAssertTrue(app.secureTextFields["Κωδικός"].waitForExistence(timeout: 2))
        app.typeText("123456789012")
        XCTAssertTrue(dismissKeyboardIfPresent())
        let submit = app.buttons["auth-submit"]
        XCTAssertTrue(waitForEnabledAndHittable(submit, timeout: 3))
        submit.tap()

        assertPaidCreditsBalance(100, timeout: 4)
        app.buttons["account-menu"].tap()
        app.buttons["Απόρρητο"].tap()
        XCTAssertTrue(app.navigationBars["Απόρρητο"].waitForExistence(timeout: 2))
        app.buttons["Τέλος"].tap()
        app.buttons["account-menu"].tap()
        app.buttons["Αποσύνδεση"].tap()
        XCTAssertTrue(app.buttons["auth-submit"].waitForExistence(timeout: 3))
    }

    func testAuthenticationErrorIsVisibleAndRecoverable() {
        launch("--gsubs-ui-test-auth-failure")
        type("ios-qa@gsubs.local", into: app.textFields["Ηλεκτρονική διεύθυνση"])
        app.typeText("\n")
        XCTAssertTrue(app.secureTextFields["Κωδικός"].waitForExistence(timeout: 2))
        app.typeText("000000000000")
        XCTAssertTrue(dismissKeyboardIfPresent())
        let submit = app.buttons["auth-submit"]
        XCTAssertTrue(waitForEnabledAndHittable(submit, timeout: 3))
        submit.tap()

        XCTAssertTrue(app.staticTexts["Λάθος email ή κωδικός."].waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["auth-submit"].isEnabled)
    }

    func testAccountDeletionCanCancelAndConfirm() {
        launch("--gsubs-ui-test-authenticated")

        app.buttons["account-menu"].tap()
        app.buttons["Διαγραφή λογαριασμού"].tap()
        XCTAssertTrue(app.alerts["Διαγραφή λογαριασμού;"].waitForExistence(timeout: 2))
        app.alerts.buttons["Ακύρωση"].tap()
        assertPaidCreditsBalance(100)

        app.buttons["account-menu"].tap()
        app.buttons["Διαγραφή λογαριασμού"].tap()
        let confirm = app.alerts.buttons["Διαγραφή"]
        XCTAssertTrue(waitForHittable(confirm, timeout: 3))
        confirm.tap()
        XCTAssertTrue(app.textFields["Ηλεκτρονική διεύθυνση"].waitForExistence(timeout: 5))
    }

    func testAccountDeletionFailureKeepsAccountUsable() {
        launch("--gsubs-ui-test-delete-failure")

        app.buttons["account-menu"].tap()
        app.buttons["Διαγραφή λογαριασμού"].tap()
        let confirm = app.alerts.buttons["Διαγραφή"]
        XCTAssertTrue(waitForHittable(confirm, timeout: 3))
        confirm.tap()

        XCTAssertTrue(
            app.staticTexts[
                "Η διαγραφή δεν ολοκληρώθηκε. Δοκίμασε ξανά."
            ].waitForExistence(timeout: 4))
        assertPaidCreditsBalance(100)
    }

    func testEditorControlsFreezeWhileAccountDeletionIsPending() {
        launch("--gsubs-ui-test-slow-delete-editor")

        let controls = [
            app.buttons["account-menu"],
            app.buttons["cue-next"],
            app.descendants(matching: .any)["subtitle-cue-0"],
            app.sliders["cue-position-slider-0"],
            app.buttons["primary-action"],
        ]
        for control in controls {
            XCTAssertTrue(waitForEnabledAndHittable(control, timeout: 3), control.debugDescription)
        }

        app.buttons["account-menu"].tap()
        app.buttons["Διαγραφή λογαριασμού"].tap()
        let confirm = app.alerts.buttons["Διαγραφή"]
        XCTAssertTrue(waitForHittable(confirm, timeout: 3))
        confirm.tap()

        XCTAssertTrue(waitForDisabled(app.buttons["primary-action"], timeout: 3))
        XCTAssertTrue(waitForAllUnavailable(controls, timeout: 3))
        attachScreenshot(named: "Editor frozen during account deletion")
    }

    func testLandscapeCloseFreezesWhileAccountDeletionIsPending() {
        launch("--gsubs-ui-test-slow-delete-editor")
        XCUIDevice.shared.orientation = .landscapeLeft

        let closeVideo = app.buttons["close-video"]
        XCTAssertTrue(waitForEnabledAndHittable(closeVideo, timeout: 3))
        XCTAssertGreaterThan(app.frame.width, app.frame.height)
        app.buttons["account-menu"].tap()
        app.buttons["Διαγραφή λογαριασμού"].tap()
        let confirm = app.alerts.buttons["Διαγραφή"]
        XCTAssertTrue(waitForHittable(confirm, timeout: 3))
        confirm.tap()

        XCTAssertTrue(waitForDisabled(app.buttons["primary-action"], timeout: 3))
        XCTAssertTrue(waitForAllUnavailable([closeVideo], timeout: 3))
        attachScreenshot(named: "Landscape close frozen during account deletion")
    }

    func testEmptyStateActionsFreezeWhileAccountDeletionIsPending() {
        launch("--gsubs-ui-test-slow-delete-empty")

        let picker = app.buttons["video-picker"]
        XCTAssertTrue(waitForEnabledAndHittable(picker, timeout: 3))
        app.buttons["account-menu"].tap()
        app.buttons["Διαγραφή λογαριασμού"].tap()
        let confirm = app.alerts.buttons["Διαγραφή"]
        XCTAssertTrue(waitForHittable(confirm, timeout: 3))
        confirm.tap()

        XCTAssertTrue(waitForDisabled(picker, timeout: 3))
        let accountMenu = app.buttons["account-menu"]
        XCTAssertTrue(waitForHittable(accountMenu, timeout: 2))
        accountMenu.tap()
        XCTAssertTrue(
            waitForAllDisabled(
                [
                    app.buttons["Διαγραφή λογαριασμού"],
                    app.buttons["Αποσύνδεση"],
                ], timeout: 3))
        attachScreenshot(named: "Empty state frozen during account deletion")
    }

    func testVideoPickerOpensAndCancels() {
        launch("--gsubs-ui-test-authenticated")
        let picker = app.buttons["video-picker"]
        XCTAssertTrue(picker.waitForExistence(timeout: 3))
        picker.tap()

        let cancel = firstExisting(
            [
                app.buttons["Cancel"],
                app.buttons["Ακύρωση"],
                app.navigationBars.buttons["Cancel"],
                app.navigationBars.buttons["Ακύρωση"],
            ], timeout: 3)
        XCTAssertNotNil(cancel)
        cancel?.tap()
        XCTAssertTrue(picker.waitForExistence(timeout: 2))
    }
}
