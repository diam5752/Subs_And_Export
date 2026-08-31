import { expect, test } from "@playwright/test";
import { mockApi, stabilizeUi, waitForUploadWorkspace } from "./mocks";
import { expectNoHorizontalOverflow, viewports } from "./support/uiTestSupport";
import el from "@/i18n/el.json";

test("Beta status and testing notice stay discreet and readable", async ({
  page,
}) => {
  await mockApi(page, { authenticated: false });
  await page.goto("/");
  await waitForUploadWorkspace(page, { authenticated: false });

  await expect(page.getByTestId("beta-badge")).toHaveText(el.betaBadge);
  await expect(page.getByText(el.betaTestingNotice)).toBeVisible();

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await stabilizeUi(page);
    await expectNoHorizontalOverflow(page);
    const badge = page.getByTestId("beta-badge");
    await expect(badge).toBeVisible();
    const badgeBox = await badge.boundingBox();
    expect(badgeBox).not.toBeNull();
    expect(badgeBox?.height ?? 0).toBeLessThanOrEqual(18);
  }
});

test("feedback chat is responsive, scroll-locked, and submits a privacy-safe path", async ({
  page,
}) => {
  await mockApi(page);
  const submissions: Array<Record<string, unknown>> = [];
  page.on("request", (request) => {
    if (
      new URL(request.url()).pathname === "/feedback" &&
      request.method() === "POST"
    ) {
      submissions.push(request.postDataJSON() as Record<string, unknown>);
    }
  });
  await page.goto("/?checkout=must-not-leak");
  await waitForUploadWorkspace(page);

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await page.getByTestId("feedback-trigger").click();
    const dialog = page.getByTestId("feedback-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute("aria-modal", "true");
    await expect(page.getByLabel(el.feedbackMessageLabel)).toBeFocused();
    await expect
      .poll(() => page.evaluate(() => document.body.style.position))
      .toBe("fixed");
    await expectNoHorizontalOverflow(page);
    const dialogBox = await dialog.boundingBox();
    expect(dialogBox).not.toBeNull();
    expect(dialogBox?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect(
      (dialogBox?.x ?? 0) + (dialogBox?.width ?? viewport.width + 1),
    ).toBeLessThanOrEqual(viewport.width + 1);
    const closeButton = page.getByRole("button", { name: el.feedbackClose });
    await closeButton.focus();
    await page.keyboard.press("Shift+Tab");
    await expect(
      page.getByRole("link", { name: el.feedbackPrivacyLink }),
    ).toBeFocused();
    await closeButton.click();
    await expect(dialog).toBeHidden();
  }

  await page.setViewportSize(viewports.mobile);
  await page.getByTestId("feedback-trigger").click();
  await page.getByRole("radio", { name: el.feedbackCategoryBug }).check();
  await page
    .getByLabel(el.feedbackMessageLabel)
    .fill("Το export κόλλησε στο τελευταίο βήμα της δοκιμής.");
  await page.waitForTimeout(2_100);
  await page.getByRole("button", { name: el.feedbackSubmit }).click();

  await expect(page.getByRole("status")).toHaveText(el.feedbackSuccess);
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0]).toMatchObject({
    category: "bug",
    source_path: "/",
    website: "",
  });
  expect(JSON.stringify(submissions[0])).not.toContain("must-not-leak");
});

test("Google Identity Services login exchanges an ID token for a GSUBS session", async ({
  page,
}) => {
  await mockApi(page, { authenticated: false });
  await page.goto("/login");

  await page.getByRole("button", { name: "Σύνδεση με Google" }).click();

  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("auth_token")))
    .toBe("google-token");
  await expect(page).toHaveURL("/");
  // REGRESSION: the authenticated header must render the profile image
  // returned after the Google session refresh.
  await expect(page.getByTestId("profile-avatar-image")).toBeVisible();
});

test("Messenger in-app browser gets a usable Google sign-in fallback", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, "userAgent", {
      configurable: true,
      get: () =>
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) " +
        "AppleWebKit/605.1.15 Mobile/15E148 " +
        "[FBAN/MessengerForiOS;FBAV/520.0.0.0.0]",
    });
  });
  let nonceRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/auth/google/nonce") {
      nonceRequests += 1;
    }
  });
  await mockApi(page, { authenticated: false });
  await page.goto("/login");

  const fallback = page.getByTestId("google-embedded-browser-fallback");
  await expect(fallback).toBeVisible();
  await expect(fallback).toContainText(el.loginGoogleEmbeddedTitle);
  await expect(fallback).toContainText(el.loginGoogleEmbeddedBody);
  await expect(page.getByTestId("google-button-container")).toHaveCount(0);
  await expect(page.getByLabel(el.loginEmailLabel)).toBeVisible();
  expect(nonceRequests).toBe(0);
});

test("expired Google nonce requires a full reload and never posts the stale credential", async ({
  page,
}) => {
  // REGRESSION: a login tab left open past the nonce TTL used to send the old
  // credential, fail with an English backend detail, and require a manual retry.
  let googleNonceRequests = 0;
  let googleCredentialPosts = 0;
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (pathname === "/auth/google/nonce") googleNonceRequests += 1;
    if (pathname === "/auth/google" && request.method() === "POST") {
      googleCredentialPosts += 1;
    }
  });

  await mockApi(page, { authenticated: false, googleNonceExpiresIn: 1 });
  await page.goto("/login");
  await expect(
    page.getByRole("button", { name: "Σύνδεση με Google" }),
  ).toBeVisible();

  await expect(page.getByRole("status")).toContainText(el.loginGoogleExpired, {
    timeout: 3_000,
  });
  await page.evaluate(() => {
    const browserWindow = window as typeof window & {
      __mockGoogleCallback?: (response: { credential?: string }) => void;
    };
    browserWindow.__mockGoogleCallback?.({
      credential: "signed-e2e-google-id-token",
    });
  });
  await page.waitForTimeout(100);
  expect(googleCredentialPosts).toBe(0);

  const mainFrameReloaded = page.waitForEvent(
    "framenavigated",
    (frame) => frame === page.mainFrame(),
  );
  await page.getByRole("button", { name: el.loginGoogleReload }).click();
  await mainFrameReloaded;
  await expect.poll(() => googleNonceRequests).toBeGreaterThanOrEqual(2);
});

test("Google sign-in stays contained when the auth viewport shrinks", async ({
  page,
}) => {
  await page.setViewportSize(viewports.desktop);
  await mockApi(page, { authenticated: false });
  await page.goto("/login");

  const googleContainer = page.getByTestId("google-button-container");
  await expect(googleContainer).toBeVisible();

  // Match the important part of the real GSI markup: its iframe can retain the
  // desktop width and includes a transparent 10px gutter on both sides.
  await googleContainer.evaluate((container) => {
    const wrapper = document.createElement("div");
    const iframe = document.createElement("iframe");
    iframe.title = "Google sign-in";
    iframe.style.width = "370px";
    iframe.style.height = "44px";
    wrapper.appendChild(iframe);
    container.replaceChildren(wrapper);
  });

  for (const viewport of [
    { width: 320, height: 568 },
    { width: 390, height: 844 },
    { width: 430, height: 932 },
    { width: 768, height: 1024 },
  ]) {
    await page.setViewportSize(viewport);
    await page.evaluate(
      () =>
        new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }),
    );

    const metrics = await page.evaluate(() => {
      const bounds = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element)
          throw new Error(`Missing responsive auth element: ${selector}`);
        const rect = element.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width };
      };

      return {
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
        main: bounds(".auth-main"),
        card: bounds(".auth-card"),
        googleContainer: bounds('[data-testid="google-button-container"]'),
        googleIframe: bounds('[data-testid="google-button-container"] iframe'),
      };
    });

    expect(
      metrics.documentOverflow,
      `${viewport.width}px document overflow`,
    ).toBeLessThanOrEqual(1);
    for (const region of [metrics.main, metrics.card, metrics.googleIframe]) {
      expect(
        region.left,
        `${viewport.width}px left containment`,
      ).toBeGreaterThanOrEqual(0);
      expect(
        region.right,
        `${viewport.width}px right containment`,
      ).toBeLessThanOrEqual(viewport.width + 1);
    }
    expect(
      metrics.googleIframe.width,
      `${viewport.width}px Google iframe width`,
    ).toBeLessThanOrEqual(metrics.googleContainer.width + 20.5);
  }
});
