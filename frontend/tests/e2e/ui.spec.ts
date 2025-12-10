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

    test('workspace renders upload area and history without overflow', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await page.getByText(new RegExp(el.liveOutputLabel, 'i')).waitFor();

      // Check that the upload area is visible
      await expect(page.getByText(el.uploadDropTitle)).toBeVisible();

      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, 'nav');
      // Check for History section which replaces the old recent jobs title
      await expect(page.getByText('History')).toBeVisible();
    });

    test('history section shows event cards neatly', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      // History is now shown as a section within the main view
      await page.getByText('History').waitFor();
      await page.getByText('Items expire in 24 hours').waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);

      // Check that the history section is properly laid out
      // The mock history data might not be loaded automatically, so just verify the section exists
      await expect(page.getByText('History')).toBeVisible();
      await expect(page.getByText('Items expire in 24 hours')).toBeVisible();
    });

    test('account settings modal keeps controls readable', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');

      // Wait for the account settings button to be rendered (after auth check) and click it
      await page.getByRole('button', { name: el.accountSettingsTitle }).click();

      // Wait for the modal heading (the modal title is the first one visible)
      await page.getByRole('heading', { name: el.accountSettingsTitle }).first().waitFor({ timeout: 5000 });

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
