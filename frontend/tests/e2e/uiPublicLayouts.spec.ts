import { expect, test } from "@playwright/test";
import {
  mockApi,
  stabilizeUi,
  waitForDashboardShell,
  waitForUploadWorkspace,
} from "./mocks";
import { expectNoHorizontalOverflow, viewports } from "./support/uiTestSupport";
import el from "@/i18n/el.json";

test("mobile public shell avoids a needless cookie consent gate and keeps the footer readable", async ({
  page,
}) => {
  // REGRESSION: the app used to show accept/decline choices even though both
  // paths enabled the same strictly necessary storage and no optional tracker.
  await page.setViewportSize({ width: 430, height: 932 });
  await mockApi(page, { authenticated: false });
  await page.goto("/");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const publicHeaderActions = page.locator(".language-toggle, .guest-sign-in");
  await expect(publicHeaderActions).toHaveCount(2);
  for (let index = 0; index < (await publicHeaderActions.count()); index += 1) {
    const box = await publicHeaderActions.nth(index).boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
    expect(box?.width).toBeGreaterThanOrEqual(44);
  }
  const footer = page.locator(".studio-footer");
  await footer.scrollIntoViewIfNeeded();
  const footerMetrics = await footer.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const links = Array.from(
      element.querySelectorAll<HTMLAnchorElement>("a"),
    ).map((link) => {
      const linkRect = link.getBoundingClientRect();
      return { left: linkRect.left, right: linkRect.right };
    });
    return {
      direction: getComputedStyle(element).flexDirection,
      left: rect.left,
      right: rect.right,
      links,
    };
  });

  expect(footerMetrics.direction).toBe("row");
  for (const link of footerMetrics.links) {
    expect(link.left).toBeGreaterThanOrEqual(footerMetrics.left);
    expect(link.right).toBeLessThanOrEqual(footerMetrics.right);
  }
});

for (const authenticated of [false, true] as const) {
  for (const viewport of [
    viewports.mobile,
    { width: 375, height: 667 },
  ] as const) {
    test(`initial mobile upload landing fits one viewport (${authenticated ? "signed in" : "signed out"}, ${viewport.width}x${viewport.height})`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await mockApi(page, { authenticated });
      await page.goto("/");
      await waitForUploadWorkspace(page, { authenticated });
      await stabilizeUi(page);

      await expect(page.locator(".app-shell")).toHaveClass(
        /app-shell-upload-landing/,
      );

      const metrics = await page.evaluate(() => {
        const bounds = (selector: string) => {
          const element = document.querySelector<HTMLElement>(selector);
          if (!element)
            throw new Error(`Missing mobile landing element: ${selector}`);
          const rect = element.getBoundingClientRect();
          return {
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
            left: rect.left,
            width: rect.width,
            height: rect.height,
          };
        };

        return {
          viewportHeight: window.innerHeight,
          pageHeight: document.documentElement.scrollHeight,
          uploadAction: bounds(".studio-upload-cta"),
          footer: bounds(".studio-footer"),
          feedback: bounds('[data-testid="feedback-trigger"]'),
        };
      });

      expect(
        metrics.pageHeight,
        `${viewport.width}x${viewport.height} mobile landing height`,
      ).toBeLessThanOrEqual(metrics.viewportHeight + 1);
      expect(
        metrics.footer.bottom,
        `${viewport.width}x${viewport.height} footer visibility`,
      ).toBeLessThanOrEqual(metrics.viewportHeight + 1);
      expect(
        metrics.uploadAction.height,
        `${viewport.width}x${viewport.height} upload touch target`,
      ).toBeGreaterThanOrEqual(44);
      expect(
        metrics.feedback.bottom,
        `${viewport.width}x${viewport.height} feedback/footer clearance`,
      ).toBeLessThanOrEqual(metrics.footer.top - 4);
    });
  }
}

for (const [label, viewport] of Object.entries(viewports)) {
  test.describe(`${label} layouts`, () => {
    test.use({ viewport });

    test("login page layout stays contained", async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto("/login");
      await page.getByRole("heading", { name: el.loginHeading }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page.getByText(el.loginSubtitle)).toBeVisible();
      await expect(
        page.getByRole("link", { name: el.legalTermsLink }),
      ).toHaveAttribute("href", "/terms");
      await expect(
        page.getByRole("link", { name: el.legalPrivacyLink }),
      ).toHaveAttribute("href", "/privacy");
      await expect(page.getByText(/Mock|€0/)).toHaveCount(0);
      if (viewport.width <= 640) {
        await expect(page.locator(".auth-promise")).toBeHidden();
      }
      if (viewport.width <= 800) {
        const headerActions = page.locator(".language-toggle, .guest-sign-in");
        for (let index = 0; index < (await headerActions.count()); index += 1) {
          const box = await headerActions.nth(index).boundingBox();
          expect(box?.height).toBeGreaterThanOrEqual(44);
          expect(box?.width).toBeGreaterThanOrEqual(44);
        }
      }
    });

    // REGRESSION: legal navigation replaced the registration page and lost
    // fields already entered by the user.
    test("register page layout stays contained", async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto("/register");
      await page.getByRole("heading", { name: el.registerTitle }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page.getByText(el.registerSubtitle)).toBeVisible();
      const legalNotice = page.locator("#register-legal-notice");
      await expect(legalNotice).toBeVisible();
      const termsLink = legalNotice.getByRole("link", {
        name: el.registerLegalTermsLink,
      });
      const privacyLink = legalNotice.getByRole("link", {
        name: el.registerLegalPrivacyLink,
      });
      await expect(termsLink).toHaveAttribute("href", "/terms");
      await expect(termsLink).toHaveAttribute("target", "_blank");
      await expect(termsLink).toHaveAttribute("rel", "noopener noreferrer");
      await expect(privacyLink).toHaveAttribute("href", "/privacy");
      await expect(privacyLink).toHaveAttribute("target", "_blank");
      await expect(privacyLink).toHaveAttribute("rel", "noopener noreferrer");
      await expect(
        page.getByRole("button", { name: el.registerSubmit }),
      ).toHaveAttribute("aria-describedby", "register-legal-notice");
      await expect(page.getByText(/Mock|€0/)).toHaveCount(0);
      if (viewport.width <= 640) {
        await expect(page.locator(".auth-promise")).toBeHidden();
      }
    });

    test("legal pages stay readable and contained", async ({ page }) => {
      const legalPages: Array<{
        path: string;
        heading: string;
        sectionHeadings: string[];
        bodyText: string | RegExp;
        absentBodyText?: RegExp;
      }> = [
        {
          path: "/privacy",
          heading: el.privacyPageTitle,
          sectionHeadings: [
            el.privacyPaymentsTitle,
            el.privacyFinancialRetentionTitle,
          ],
          bodyText: el.privacyFinancialRetentionBody,
        },
        {
          path: "/terms",
          heading: el.termsPageTitle,
          sectionHeadings: [el.termsSellerTitle, el.termsPaidCreditsScopeTitle],
          bodyText: el.termsPaidCreditsScopeBody,
        },
      ];
      for (const legalPage of legalPages) {
        await page.goto(legalPage.path);
        await page.getByRole("heading", { name: legalPage.heading }).waitFor();
        await stabilizeUi(page);
        await expectNoHorizontalOverflow(page);
        await expect(
          page.getByRole("link", { name: el.brandHomeLabel }),
        ).toBeVisible();
        await expect(
          page.getByRole("button", {
            name: new RegExp(el.switchLanguage.split("{")[0]),
          }),
        ).toBeVisible();
        if (viewport.width <= 800) {
          const languageBox = await page
            .locator(".language-toggle")
            .boundingBox();
          expect(languageBox?.height).toBeGreaterThanOrEqual(44);
          expect(languageBox?.width).toBeGreaterThanOrEqual(44);
        }
        for (const sectionHeading of legalPage.sectionHeadings) {
          await expect(
            page.getByRole("heading", { name: sectionHeading }),
          ).toBeVisible();
        }
        await expect(page.getByText(legalPage.bodyText)).toBeVisible();
        if (legalPage.absentBodyText) {
          await expect(page.getByText(legalPage.absentBodyText)).toHaveCount(0);
        }
      }
    });

    test("workspace renders upload area without overflow", async ({ page }) => {
      await mockApi(page);
      await page.goto("/");
      await waitForUploadWorkspace(page);
      const uploadSection = page.getByTestId("upload-section");
      await uploadSection.waitFor({ state: "visible" });

      // Check that the upload area is visible regardless of whether it is
      // rendering the full dropzone or the compact restored-session view.
      await expect(uploadSection).toBeVisible();
      await expect(page.getByTestId("credits-balance")).toContainText("125");
      await expect(page.getByTestId("credits-coin-icon")).toBeVisible();
      await expect(page.getByTestId("app-env-badge")).toHaveCount(0);
      await expect(page.getByTestId("mock-mode-badge")).toHaveCount(0);
      await expect(page.getByTestId("engine-settings-toggle")).toHaveCount(0);
      await expect(page.getByText("Δες έτοιμο παράδειγμα")).toHaveCount(0);
      await expect(
        page.locator(".studio-nav").getByText(el.accountSettingsTitle),
      ).toHaveCount(0);

      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, "nav");
    });

    test("completed preview stays contained without overflow", async ({
      page,
    }) => {
      await mockApi(page);
      await page.addInitScript(() => {
        localStorage.setItem("lastActiveJobId", "job-futurist");
      });
      await page.goto("/");

      await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, "main");
      await expect(page.getByText(el.subtitlesReady)).toHaveCount(0);
      await expect(page.getByTestId("completed-editor")).toBeVisible();
      await expect(
        page.getByRole("tab", { name: el.tabTranscript }),
      ).toBeVisible();
      await expect(page.getByRole("tab", { name: el.tabStyles })).toBeVisible();
      await expect(page.getByText("Mock Studio")).toHaveCount(0);
    });

    test("history section shows event cards neatly", async ({ page }) => {
      await mockApi(page);
      await page.goto("/");
      await waitForDashboardShell(page);
      await expect(
        page
          .getByRole("banner", { name: "gsubs studio" })
          .getByRole("button", { name: el.historyTitle }),
      ).toHaveCount(0);
      await page.getByRole("button", { name: el.profileLabel }).click();
      await page.getByRole("button", { name: el.historyTitle }).click();
      await page.getByRole("heading", { name: el.historyTitle }).waitFor();
      await page.getByText(el.historyExpiry).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);

      // Check that the history section is properly laid out
      // The mock history data might not be loaded automatically, so just verify the section exists
      await expect(
        page.getByRole("heading", { name: el.historyTitle }),
      ).toBeVisible();
      await expect(page.getByText(el.historyExpiry)).toBeVisible();
      if (viewport.width <= 800) {
        const historyDialog = page.getByRole("dialog", {
          name: el.historyTitle,
        });
        const selectionBox = await page
          .getByRole("button", { name: el.selectMode })
          .boundingBox();
        expect(selectionBox?.height).toBeGreaterThanOrEqual(44);
        expect(selectionBox?.width).toBeGreaterThanOrEqual(44);

        const historyDownload = historyDialog
          .getByRole("button", {
            name: new RegExp(`^${el.download} `),
          })
          .first();
        const historyView = historyDialog
          .getByRole("button", {
            name: new RegExp(`^${el.view} `),
          })
          .first();
        const historyDelete = historyDialog
          .getByRole("button", {
            name: new RegExp(`^${el.deleteJob} `),
          })
          .first();
        const itemActions = [historyDownload, historyView, historyDelete];
        for (let index = 0; index < itemActions.length; index += 1) {
          await expect(itemActions[index]).toBeVisible();
          const box = await itemActions[index].boundingBox();
          expect(
            box?.height,
            `history item action ${index} height`,
          ).toBeGreaterThanOrEqual(44);
          expect(
            box?.width,
            `history item action ${index} width`,
          ).toBeGreaterThanOrEqual(44);
        }
        const historyCard = historyView.locator("..").locator("..");
        const historyLayout = await historyCard.evaluate((element) => {
          const metadata = element.firstElementChild as HTMLElement;
          const actions = element.querySelector<HTMLElement>(
            ".recent-job-actions",
          )!;
          const metadataRect = metadata.getBoundingClientRect();
          const actionsRect = actions.getBoundingClientRect();
          return {
            metadataWidth: metadataRect.width,
            metadataBottom: metadataRect.bottom,
            actionsTop: actionsRect.top,
          };
        });
        expect(historyLayout.metadataWidth).toBeGreaterThanOrEqual(240);
        expect(historyLayout.actionsTop).toBeGreaterThanOrEqual(
          historyLayout.metadataBottom,
        );

        await historyDelete.click();
        const confirmationActions = [
          historyDialog.getByRole("button", {
            name: new RegExp(`^${el.confirmDelete} `),
          }),
          historyDialog.getByRole("button", { name: el.cancel }),
        ];
        for (let index = 0; index < confirmationActions.length; index += 1) {
          await expect(confirmationActions[index]).toBeVisible();
          const box = await confirmationActions[index].boundingBox();
          expect(
            box?.height,
            `history confirmation action ${index} height`,
          ).toBeGreaterThanOrEqual(44);
          expect(
            box?.width,
            `history confirmation action ${index} width`,
          ).toBeGreaterThanOrEqual(44);
        }
      }
    });

    test("account settings modal keeps controls readable", async ({ page }) => {
      await mockApi(page);
      await page.goto("/");
      await waitForDashboardShell(page);

      // Wait for the account settings button to be rendered (after auth check) and click it
      await page.getByRole("button", { name: el.profileLabel }).click();

      // Wait for the modal heading (the modal title is the first one visible)
      const dialog = page.getByRole("dialog", {
        name: el.accountSettingsTitle,
      });
      await dialog.waitFor({ timeout: 5000 });

      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(
        dialog.getByRole("button", { name: el.closeLabel }),
      ).toBeFocused();
      await expect(page.getByText(el.accountSettingsSubtitle)).toBeVisible();
      await expect(dialog.getByText(el.deleteAccountDescription)).toBeVisible();
      await dialog.getByRole("button", { name: el.deleteAccount }).click();
      await expect(dialog.getByText(el.deleteAccountConfirm)).toBeVisible();

      const closeButton = dialog.getByRole("button", { name: el.closeLabel });
      const closeBounds = await closeButton.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      });
      expect(closeBounds.width).toBeGreaterThanOrEqual(44);
      expect(closeBounds.height).toBeGreaterThanOrEqual(44);
      if (viewport.width <= 800) {
        const buttons = dialog.getByRole("button");
        for (let index = 0; index < (await buttons.count()); index += 1) {
          const box = await buttons.nth(index).boundingBox();
          if (!box) continue;
          expect(
            box.height,
            `account dialog button ${index} height`,
          ).toBeGreaterThanOrEqual(44);
          expect(
            box.width,
            `account dialog button ${index} width`,
          ).toBeGreaterThanOrEqual(44);
        }
      }
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: el.profileLabel }),
      ).toBeFocused();
    });
  });
}

test("unauthenticated users can open the upload workspace before login", async ({
  page,
}) => {
  await mockApi(page, { authenticated: false });
  await page.goto("/");
  await waitForUploadWorkspace(page, { authenticated: false });

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("upload-section")).toBeVisible();
  await expect(
    page.getByText(
      el.uploadDropFootnote
        .replace("{size}", "500")
        .replace("{duration}", "3:00"),
    ),
  ).toBeVisible();
  const signInLink = page.getByRole("link", { name: el.guestSignIn });
  await expect(signInLink).toBeVisible();
  await expect(signInLink).toHaveAttribute("href", "/login");
  await signInLink.click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: el.profileLabel })).toHaveCount(
    0,
  );
});

// REGRESSION: signing out while the account dialog was open left the header
// inert, making the newly rendered sign-in link impossible to click.
test("sign-in remains interactive after logout from the account dialog", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/");
  await waitForDashboardShell(page);

  await page.getByRole("button", { name: el.profileLabel }).click();
  const dialog = page.getByRole("dialog", { name: el.accountSettingsTitle });
  const logoutRequestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/auth/logout"),
  );
  await dialog.getByRole("button", { name: el.signOut }).click();
  const logoutRequest = await logoutRequestPromise;

  expect(logoutRequest.headers().authorization).toBe("Bearer test-token");
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("auth_token")))
    .toBeNull();
  const signInLink = page.getByRole("link", { name: el.guestSignIn });
  await expect(signInLink).toBeVisible();
  await signInLink.click();
  await expect(page).toHaveURL(/\/login$/);
});
