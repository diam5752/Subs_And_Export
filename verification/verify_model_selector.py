from playwright.sync_api import Page, expect, sync_playwright

def verify_model_selector():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # We need to mock the backend and auth to bypass login
        page.route('**/api/v1/auth/me', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body='{"id": "user123", "email": "test@example.com", "full_name": "Test User", "is_active": true, "is_superuser": false}'
        ))

        page.route('**/api/v1/videos/jobs*', lambda route: route.fulfill(
            status=200,
            body='[]'
        ))

        # Navigate to the main page
        page.goto('http://localhost:3000/')

        # Wait for Step 1
        expect(page.get_by_text('STEP 1')).to_be_visible()

        # Check for our new buttons
        # 1. Main toggle button
        main_button = page.locator('button').filter(has_text='STEP 1')
        expect(main_button).to_be_visible()

        # 2. Tooltip button
        tooltip_button = page.get_by_role('button', name='Model comparison information')
        expect(tooltip_button).to_be_visible()

        # 3. Chevron button
        # There might be multiple chevrons (one for Step 2 as well), so get the first one or filter by parent
        # The parent of the step 1 chevron is in the same row as STEP 1
        chevron_button = page.locator('button').filter(has=page.locator('[data-testid="step-1-chevron"]'))
        expect(chevron_button).to_be_visible()

        # Take screenshot
        page.screenshot(path='verification.png', full_page=True)
        print("Verification screenshot saved to verification.png")

        browser.close()

if __name__ == "__main__":
    verify_model_selector()
