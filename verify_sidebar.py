import time
from playwright.sync_api import sync_playwright

def verify_sidebar():
    with sync_playwright() as p:
        print("Launching browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 720}
        )

        # Force English locale via cookie
        context.add_cookies([{
            "name": "NEXT_LOCALE",
            "value": "en",
            "domain": "localhost",
            "path": "/"
        }])

        page = context.new_page()

        # 1. Register
        print("Navigating to register page (http://localhost:3002/register)...")
        try:
            page.goto("http://localhost:3002/register", timeout=30000)
        except Exception as e:
            print(f"Error navigating: {e}")
            page.screenshot(path="nav_error.png")
            browser.close()
            return

        print("Filling registration form...")
        try:
            page.wait_for_selector("#name", state="visible")
            page.fill("#name", "Test User")
            page.fill("#email", f"bolt_{int(time.time())}@example.com")
            # Password must be at least 12 characters
            page.fill("#password", "password123456")

            print("Submitting...")
            page.click("button[type='submit']")

            # Wait for redirection to dashboard
            print("Waiting for dashboard...")
            # Dashboard is usually /
            page.wait_for_url("http://localhost:3002/", timeout=30000)
            print("Redirected to dashboard successfully.")

            # Screenshot dashboard
            time.sleep(2) # Wait for animations/load
            page.screenshot(path="dashboard.png")
            print("Saved dashboard.png")

            # 2. Navigate to Process View
            # Usually there is a "New Job" or similar button, or we can go directly to / (dashboard IS where new job starts?)
            # Let's check if we see the sidebar components (e.g. "Presets", "Subtitle Position")
            # If the dashboard has the ProcessView, we should see it.

            # Check for text "Customize" or "Presets" or specific IDs if we added them.
            # But the Sidebar is usually only visible if we have a video loaded?
            # Or is it always visible in "ProcessView"?

            # Wait, the ProcessView usually requires a file to be selected first?
            # Or maybe we can see the empty state.

            # Let's try to find "Style Presets" text.
            content = page.content()
            if "Style Presets" in content:
                print("Found 'Style Presets' in DOM.")
            else:
                print("Did not find 'Style Presets'. Might need to upload video first.")

        except Exception as e:
            print(f"Error during registration: {e}")
            page.screenshot(path="error.png")
            print("Saved error.png")

        finally:
            browser.close()

if __name__ == "__main__":
    verify_sidebar()
