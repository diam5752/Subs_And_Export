import { expect, test } from "@playwright/test";
import el from "@/i18n/el.json";
import { mockApi } from "./mocks";

test("gsubs branding is visible across the public shell and metadata", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/");

  const header = page.getByRole("banner", { name: "gsubs studio" });
  const headerLogo = header.getByRole("img", { name: "gsubs" });
  await expect(headerLogo).toBeVisible();
  // REGRESSION: The owner-selected stacked logo was replaced by a horizontal
  // compact-split pill across the public routes.
  await expect(headerLogo).toHaveAttribute("src", "/brand/gsubs-logo.svg");
  // Leave room for the discreet Beta pill without increasing the 72px header.
  await expect(headerLogo).toHaveCSS("width", "72px");
  const footerLogo = page.locator(".footer-brand img");
  await expect(footerLogo).toBeVisible();
  await expect(footerLogo).toHaveAttribute("src", "/brand/gsubs-logo.svg");
  await expect(footerLogo).toHaveCSS("width", "68px");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(headerLogo).toHaveCSS("width", "68px");
  await expect(headerLogo).toBeVisible();
  await expect(page).toHaveTitle("gsubs · Subtitle Studio");

  // REGRESSION: Social apps fell back to the square PWA icon, enlarged it and
  // cropped the logo instead of receiving a deliberate wide share card.
  const socialImage = "https://gsubs.gr/brand/gsubs-social-card.png";
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
    "content",
    socialImage,
  );
  await expect(page.locator('meta[property="og:image:width"]')).toHaveAttribute(
    "content",
    "1200",
  );
  await expect(
    page.locator('meta[property="og:image:height"]'),
  ).toHaveAttribute("content", "630");
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
    "content",
    "summary_large_image",
  );
  await expect(page.locator('meta[name="twitter:image"]')).toHaveAttribute(
    "content",
    socialImage,
  );

  const socialCardResponse = await page.request.get(
    "/brand/gsubs-social-card.png",
  );
  expect(socialCardResponse.ok()).toBe(true);
  expect(socialCardResponse.headers()["content-type"]).toContain("image/png");
  const socialCard = await socialCardResponse.body();
  expect(socialCard.readUInt32BE(16)).toBe(1200);
  expect(socialCard.readUInt32BE(20)).toBe(630);

  const manifestResponse = await page.request.get("/manifest.webmanifest");
  expect(manifestResponse.ok()).toBe(true);
  const manifest = await manifestResponse.json();
  expect(manifest).toMatchObject({
    name: "gsubs · Subtitle Studio",
    short_name: "gsubs",
  });

  for (const asset of [
    "/brand/gsubs-logo.svg",
    "/brand/gsubs-mark.svg",
    "/brand/gsubs-social-card.svg",
    "/brand/gsubs-social-card.png",
    "/gsubs-watermark.png",
    "/icon.png",
    "/apple-icon.png",
  ]) {
    const response = await page.request.get(asset);
    expect(response.ok(), asset).toBe(true);
    expect(
      Number(response.headers()["content-length"] ?? 1),
      asset,
    ).toBeGreaterThan(0);
  }
});

test("gsubs identity remains visible on auth and legal routes", async ({
  page,
}) => {
  await mockApi(page, { authenticated: false });

  for (const route of ["/login", "/register", "/privacy", "/terms"]) {
    await page.goto(route);
    await expect(
      page.getByRole("img", { name: "gsubs" }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: "gsubs" }).first(),
    ).toHaveAttribute("src", "/brand/gsubs-logo.svg");
  }
});

test("the editor keeps advanced output toggles out of the style workspace", async ({
  page,
}) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });

  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await page.getByRole("tab", { name: el.tabStyles }).click();
  await expect(page.getByRole("switch")).toHaveCount(0);
  await expect(
    page.getByText("Λειτουργία Karaoke", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("Badge Συνεργάτη", { exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByRole("img", { name: "gsubs watermark" })).toHaveCount(
    0,
  );
});
