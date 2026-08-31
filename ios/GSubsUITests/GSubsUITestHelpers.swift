import XCTest

extension GSubsUITests {
    func launch(_ argument: String, contentSizeCategory: String? = nil) {
        app = XCUIApplication()
        app.launchArguments = [argument]
        if let contentSizeCategory {
            app.launchArguments += [
                "-UIPreferredContentSizeCategoryName",
                contentSizeCategory,
            ]
        }
        app.launch()
    }

    func type(_ text: String, into element: XCUIElement) {
        XCTAssertTrue(dismissKeyboardIfPresent())
        XCTAssertTrue(waitAndReveal(element, timeout: 3), element.debugDescription)
        element.tap()
        XCTAssertTrue(
            app.keyboards.firstMatch.waitForExistence(timeout: 2),
            element.debugDescription
        )
        element.typeText(text)
    }

    func openAndClosePrivacy() {
        app.buttons["privacy-details"].tap()
        XCTAssertTrue(app.navigationBars["Απόρρητο"].waitForExistence(timeout: 2))
        XCTAssertTrue(app.staticTexts["Στέλνεται μόνο ήχος"].exists)
        let privacyLink = app.descendants(matching: .any)["privacy-policy-link"]
        XCTAssertTrue(waitAndReveal(privacyLink, timeout: 5), privacyLink.debugDescription)
        app.buttons["Τέλος"].tap()
    }

    func dismissPasswordSavePromptIfPresent(timeout: TimeInterval) {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let candidates = [
            app.buttons["Not Now"],
            app.buttons["Όχι τώρα"],
            springboard.buttons["Not Now"],
            springboard.buttons["Όχι τώρα"],
        ]
        guard let dismiss = firstExisting(candidates, timeout: timeout) else { return }
        XCTAssertTrue(waitForHittable(dismiss, timeout: 2), dismiss.debugDescription)
        dismiss.tap()
        XCTAssertTrue(dismiss.waitForNonExistence(timeout: 2), dismiss.debugDescription)
    }

    func assertPaidCreditsBalance(
        _ balance: Int,
        timeout: TimeInterval = 2,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let expectedLabel = "\(balance) διαθέσιμα πληρωμένα credits"
        let credits = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@", expectedLabel))
            .firstMatch
        XCTAssertTrue(credits.waitForExistence(timeout: timeout), file: file, line: line)
        XCTAssertEqual(credits.label, expectedLabel, file: file, line: line)
    }

    func firstExisting(
        _ candidates: [XCUIElement],
        timeout: TimeInterval
    ) -> XCUIElement? {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let element = candidates.first(where: \.exists) { return element }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        return nil
    }

    func waitForHittable(
        _ element: XCUIElement,
        timeout: TimeInterval
    ) -> Bool {
        let predicate = NSPredicate(format: "exists == true AND hittable == true")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    func waitForEnabledAndHittable(
        _ element: XCUIElement,
        timeout: TimeInterval
    ) -> Bool {
        let predicate = NSPredicate(
            format: "exists == true AND enabled == true AND hittable == true"
        )
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    func waitForDisabled(
        _ element: XCUIElement,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.exists, !element.isEnabled { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        return element.exists && !element.isEnabled
    }

    func waitForAllDisabled(
        _ elements: [XCUIElement],
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if elements.allSatisfy({ $0.exists && !$0.isEnabled }) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        return elements.allSatisfy { $0.exists && !$0.isEnabled }
    }

    func waitForAllUnavailable(
        _ elements: [XCUIElement],
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if elements.allSatisfy({ $0.exists && (!$0.isEnabled || !$0.isHittable) }) {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        return elements.allSatisfy { $0.exists && (!$0.isEnabled || !$0.isHittable) }
    }

    func waitForShareSurface(
        activityList: XCUIElement,
        obscuredButton: XCUIElement,
        closeCandidates: [XCUIElement],
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if activityList.exists
                || !obscuredButton.isHittable
                || closeCandidates.contains(where: \.exists)
            {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        return activityList.exists
            || !obscuredButton.isHittable
            || closeCandidates.contains(where: \.exists)
    }

    func waitForStableFrame(
        _ element: XCUIElement,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        var previous: CGRect?
        var stableSamples = 0
        while Date() < deadline {
            guard element.exists else { return false }
            let current = element.frame
            if let previous, framesAreClose(previous, current) {
                stableSamples += 1
                if stableSamples >= 2 { return true }
            } else {
                stableSamples = 0
            }
            previous = current
            RunLoop.current.run(until: Date().addingTimeInterval(0.08))
        }
        return false
    }

    func framesAreClose(_ lhs: CGRect, _ rhs: CGRect) -> Bool {
        abs(lhs.minX - rhs.minX) <= 0.5
            && abs(lhs.minY - rhs.minY) <= 0.5
            && abs(lhs.width - rhs.width) <= 0.5
            && abs(lhs.height - rhs.height) <= 0.5
    }

    func assertVerticallyOrderedAndContained(
        _ elements: [XCUIElement],
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let appFrame = app.frame
        for element in elements {
            XCTAssertGreaterThanOrEqual(
                element.frame.minX,
                appFrame.minX - 1,
                file: file,
                line: line
            )
            XCTAssertLessThanOrEqual(
                element.frame.maxX,
                appFrame.maxX + 1,
                file: file,
                line: line
            )
            XCTAssertGreaterThanOrEqual(
                element.frame.minY,
                appFrame.minY - 1,
                file: file,
                line: line
            )
            XCTAssertLessThanOrEqual(
                element.frame.maxY,
                appFrame.maxY + 1,
                file: file,
                line: line
            )
        }
        for (upper, lower) in zip(elements, elements.dropFirst()) {
            XCTAssertLessThanOrEqual(
                upper.frame.maxY,
                lower.frame.minY + 1,
                file: file,
                line: line
            )
        }
    }

    func dismissKeyboardIfPresent(timeout: TimeInterval = 2) -> Bool {
        let keyboard = app.keyboards.firstMatch
        guard keyboard.exists else { return true }
        let done = app.buttons["keyboard-done"]
        if done.waitForExistence(timeout: 1), done.isHittable {
            done.tap()
            if keyboard.waitForNonExistence(timeout: timeout) { return true }
        }
        app.swipeUp()
        if keyboard.waitForNonExistence(timeout: 1) { return true }
        app.swipeDown()
        return keyboard.waitForNonExistence(timeout: timeout)
    }

    func waitForValue(
        _ element: XCUIElement,
        equals value: String,
        timeout: TimeInterval
    ) -> Bool {
        let predicate = NSPredicate(format: "value == %@", value)
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    func waitForLabel(
        _ element: XCUIElement,
        equals label: String,
        timeout: TimeInterval
    ) -> Bool {
        let predicate = NSPredicate(format: "label == %@", label)
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    func waitForLabel(
        _ element: XCUIElement,
        contains label: String,
        timeout: TimeInterval
    ) -> Bool {
        let predicate = NSPredicate(format: "label CONTAINS %@", label)
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    func waitForValue(
        _ element: XCUIElement,
        beginsWith value: String,
        timeout: TimeInterval
    ) -> Bool {
        let predicate = NSPredicate(format: "value BEGINSWITH %@", value)
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    func percentage(in element: XCUIElement) -> Int? {
        guard let value = element.value as? String,
            let range = value.range(of: #"\d+(?=%)"#, options: .regularExpression)
        else {
            return nil
        }
        return Int(value[range])
    }

    func attachScreenshot(named name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func reveal(_ element: XCUIElement, swipes: Int = 8) -> Bool {
        if isSafelyHittable(element) { return true }
        for _ in 0..<swipes {
            app.swipeUp()
            if waitForSafelyHittable(element, timeout: 0.5) { return true }
        }
        return false
    }

    func waitForSafelyHittable(
        _ element: XCUIElement,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if isSafelyHittable(element) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        return false
    }

    func isSafelyHittable(_ element: XCUIElement) -> Bool {
        guard element.exists, element.isHittable else { return false }
        let stickyAction = app.buttons["primary-action"]
        guard stickyAction.exists, element.identifier != "primary-action" else {
            return true
        }
        return element.frame.maxY <= stickyAction.frame.minY - 8
    }

    func revealUp(_ element: XCUIElement, swipes: Int = 8) -> Bool {
        if element.exists && element.isHittable { return true }
        for _ in 0..<swipes {
            app.swipeDown()
            if element.exists && element.isHittable { return true }
        }
        return false
    }

    func waitAndReveal(
        _ element: XCUIElement,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if reveal(element, swipes: 1) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }

    func allowPhotoWriteIfPrompted(action: () -> Void) {
        addUIInterruptionMonitor(withDescription: "Photo add permission") { alert in
            let allowButtons = [
                alert.buttons["Allow"],
                alert.buttons["Allow Access to All Photos"],
                alert.buttons["Να επιτρέπεται"],
            ]
            guard let button = allowButtons.first(where: \.exists) else { return false }
            button.tap()
            return true
        }
        action()
        app.tap()
    }
}
