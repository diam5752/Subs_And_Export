import { expect, test } from "@playwright/test";
import el from "@/i18n/el.json";
import { mockApi } from "./mocks";

test("checkout return stays visible and ignores a stale pre-purchase balance", async ({
  page,
}) => {
  const sessionId = "cs_test_mobile_return";
  let releaseStaleBalance!: () => void;
  let releasePaidStatus!: () => void;
  let markStaleBalanceStarted!: () => void;
  const staleBalanceRelease = new Promise<void>((resolve) => {
    releaseStaleBalance = resolve;
  });
  const paidStatusRelease = new Promise<void>((resolve) => {
    releasePaidStatus = resolve;
  });
  const staleBalanceStarted = new Promise<void>((resolve) => {
    markStaleBalanceStarted = resolve;
  });

  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.route("**/auth/points", async (route) => {
    markStaleBalanceStarted();
    await staleBalanceRelease;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        balance: 800,
        paid_balance: 330,
        promotional_balance: 470,
        reversal_debt: 0,
        ai_spendable_balance: 330,
      }),
    });
  });
  await page.route(`**/billing/checkout/${sessionId}`, async (route) => {
    await paidStatusRelease;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        purchase_id: "purchase-mobile-return",
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status: "paid",
        checkout_session_id: sessionId,
        wallet: {
          balance: 900,
          paid_balance: 430,
          promotional_balance: 470,
          reversal_debt: 0,
          ai_spendable_balance: 430,
        },
      }),
    });
  });

  await page.goto(`/?checkout=success&session_id=${sessionId}`);
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await staleBalanceStarted;
  await page.evaluate(() =>
    window.scrollTo(0, document.documentElement.scrollHeight),
  );

  const notice = page.getByTestId("checkout-return-notice");
  await expect(notice).toContainText(el.creditPurchasePending);
  await expect(notice).toBeInViewport();
  const pendingBounds = await notice.boundingBox();
  const headerBounds = await page.locator(".studio-header").boundingBox();
  if (!pendingBounds || !headerBounds) {
    throw new Error(
      "Expected the checkout notice and fixed header to have viewport bounds.",
    );
  }
  expect(pendingBounds.y).toBeGreaterThanOrEqual(
    headerBounds.y + headerBounds.height,
  );

  releasePaidStatus();

  await expect(notice).toContainText(
    el.creditPurchaseSuccess
      .replace("{count}", "100")
      .replace("{balance}", "900"),
  );
  await expect(notice).toHaveAttribute("data-kind", "success");
  await expect(notice).toBeInViewport();
  await expect(page.getByTestId("credits-balance")).toContainText("900");

  const staleResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/auth/points") && response.status() === 200,
  );
  releaseStaleBalance();
  const response = await staleResponse;
  await response.finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );

  await expect(page.getByTestId("credits-balance")).toContainText("900");
  await expect.poll(() => new URL(page.url()).search).toBe("");
});
