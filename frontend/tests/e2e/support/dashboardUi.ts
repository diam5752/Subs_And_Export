import { Page } from "@playwright/test";
import el from "@/i18n/el.json";

export async function stabilizeUi(page: Page): Promise<void> {
  // The product deliberately keeps short-lived presence and job polling alive.
  // Wait for the document and the rendered surface instead of a global network
  // state that a healthy, observable application does not promise to reach.
  await page.waitForLoadState("domcontentloaded");
  await page.evaluate(async () => {
    if ("fonts" in document) {
      await document.fonts.ready;
    }
  });
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        transition-duration: 0s !important;
        animation-duration: 0s !important;
        caret-color: transparent !important;
      }
      video { background: #000 !important; }
    `,
  });
}

export async function waitForDashboardShell(page: Page): Promise<void> {
  await page.waitForLoadState("domcontentloaded");
  await page.getByRole("button", { name: el.profileLabel }).waitFor({
    state: "visible",
    timeout: 30_000,
  });
}

export async function waitForUploadWorkspace(
  page: Page,
  options: { authenticated?: boolean } = {},
): Promise<void> {
  const { authenticated = true } = options;
  await page.waitForLoadState("domcontentloaded");
  if (authenticated) {
    await waitForDashboardShell(page);
  } else {
    await page.getByRole("link", { name: el.guestSignIn }).waitFor({
      state: "visible",
      timeout: 30_000,
    });
  }
  await page.getByTestId("upload-section").waitFor({
    state: "visible",
    timeout: 30_000,
  });
}
