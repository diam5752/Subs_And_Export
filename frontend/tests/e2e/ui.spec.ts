import { expect, test, type Locator, type Page } from '@playwright/test';
import { mockApi, stabilizeUi } from './mocks';
import el from '@/i18n/el.json';

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
  test.describe(`${label} layouts`, () => {
    test.use({ viewport });

    test('login page layout stays contained', async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto('/login');
      await page.getByRole('heading', { name: el.loginHeading }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page.getByText(el.loginSubtitle)).toBeVisible();
    });

    test('register page layout stays contained', async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto('/register');
      await page.getByRole('heading', { name: el.registerTitle }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page.getByText(el.registerSubtitle)).toBeVisible();
    });

    test('workspace tab renders jobs and settings without overflow', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await page.getByRole('button', { name: el.tabWorkspace }).waitFor();
      await page.getByText(new RegExp(el.liveOutputLabel, 'i')).waitFor();

      const fileInput = page.locator('input[type="file"]');
      await fileInput.setInputFiles({
        name: 'sample-video.mp4',
        mimeType: 'video/mp4',
        buffer: Buffer.alloc(120 * 1024),
      });

      await page.getByRole('button', { name: el.controlsShowDetails }).click();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, 'nav');
      const longJobCard = page.getByTestId('recent-job-job-long-form');
      await longJobCard.waitFor();
      await expectLocatorWithinBounds(longJobCard);
      await expect(page.getByText(el.recentJobsTitle)).toBeVisible();
    });

    test('history tab shows event cards neatly', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await page.getByRole('button', { name: el.tabHistory }).click();
      await page.getByRole('heading', { name: el.activityTitle }).waitFor();
      await page.getByText('Completed reel with safe subtitle margins').waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      const summaryRow = page.getByTestId('job-summary-job-long-form');
      await summaryRow.waitFor();
      await expectLocatorWithinBounds(summaryRow);
      await expect(page.getByText(el.timelineLabel)).toBeVisible();
    });

    test('account tab keeps controls and history readable', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await page.getByRole('button', { name: el.tabAccount }).click();
      await page.getByRole('heading', { name: el.accountSettingsTitle }).waitFor();
      await page.getByText(el.recentHistoryLabel).waitFor();
      await page.getByText('Signed in from Chrome on macOS').waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page.getByText(el.accountSettingsSubtitle)).toBeVisible();
    });
  });
}

test('unauthenticated users are redirected to login', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/');
  await page.waitForURL('**/login');
  await expect(page).toHaveURL(/\/login$/);
});
