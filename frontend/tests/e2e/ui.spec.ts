import { expect, test, type Locator, type Page } from '@playwright/test';
import { mockApi, stabilizeUi } from './mocks';

const viewports = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
} as const;

async function expectNoHorizontalOverflow(page: Page, selector?: string) {
  const overflow = await page.evaluate((sel) => {
    const target = sel ? document.querySelector<HTMLElement>(sel) : document.documentElement;
    if (!target) return 0;
    const clientWidth = target.clientWidth || window.innerWidth;
    return target.scrollWidth - clientWidth;
  }, selector);
  expect(overflow).toBeLessThanOrEqual(1);
}

async function expectLocatorWithinBounds(locator: Locator) {
  const overflow = await locator.evaluate((node) => {
    const el = node as HTMLElement;
    return el.scrollWidth - el.clientWidth;
  });
  expect(overflow).toBeLessThanOrEqual(1);
}

for (const [label, viewport] of Object.entries(viewports)) {
  test.describe(`${label} snapshots`, () => {
    test.use({ viewport });

    test('login page layout stays contained', async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto('/login');
      await page.getByRole('heading', { name: /sign in to your account/i }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page).toHaveScreenshot(`login-${label}.png`, { fullPage: true });
    });

    test('register page layout stays contained', async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto('/register');
      await page.getByRole('heading', { name: /create account/i }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page).toHaveScreenshot(`register-${label}.png`, { fullPage: true });
    });

    test('workspace tab renders jobs and settings without overflow', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await page.getByRole('button', { name: 'Workspace' }).waitFor();
      await page.getByText(/Live output/i).waitFor();

      const fileInput = page.locator('input[type="file"]');
      await fileInput.setInputFiles({
        name: 'sample-video.mp4',
        mimeType: 'video/mp4',
        buffer: Buffer.alloc(120 * 1024),
      });

      await page.getByRole('button', { name: /tune detail/i }).click();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, 'nav');
      const longJobCard = page.getByTestId('recent-job-job-long-form');
      await longJobCard.waitFor();
      await expectLocatorWithinBounds(longJobCard);
      await expect(page).toHaveScreenshot(`dashboard-process-${label}.png`, { fullPage: true });
    });

    test('history tab shows event cards neatly', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await page.getByRole('button', { name: 'History' }).click();
      await page.getByRole('heading', { name: /Activity/i }).waitFor();
      await page.getByText('Completed reel with safe subtitle margins').waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      const summaryRow = page.getByTestId('job-summary-job-long-form');
      await summaryRow.waitFor();
      await expectLocatorWithinBounds(summaryRow);
      await expect(page).toHaveScreenshot(`dashboard-history-${label}.png`, {
        fullPage: true,
        // Allow a bit more cross-platform rendering variance for this view (fonts/AA drift).
        maxDiffPixelRatio: 0.04,
      });
    });

    test('account tab keeps controls and history readable', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await page.getByRole('button', { name: 'Account' }).click();
      await page.getByRole('heading', { name: 'Account settings' }).waitFor();
      await page.getByText('Recent history').waitFor();
      await page.getByText('Signed in from Chrome on macOS').waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page).toHaveScreenshot(`dashboard-account-${label}.png`, { fullPage: true });
    });
  });
}

test('unauthenticated users are redirected to login', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/');
  await page.waitForURL('**/login');
  await expect(page).toHaveURL(/\/login$/);
});
