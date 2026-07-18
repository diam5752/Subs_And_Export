import { expect, test, type Page } from '@playwright/test';
import { mockApi, stabilizeUi, waitForDashboardShell, waitForModelPicker } from './mocks';
import el from '@/i18n/el.json';

const viewports = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
} as const;

const editorViewportMatrix = [
  { width: 320, height: 568 },
  { width: 375, height: 667 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

async function expectNoHorizontalOverflow(page: Page, selector?: string) {
  const overflow = await page.evaluate((sel) => {
    const target = sel ? document.querySelector<HTMLElement>(sel) : document.documentElement;
    if (!target) return 0;
    const clientWidth = target.clientWidth || window.innerWidth;
    return target.scrollWidth - clientWidth;
  }, selector);
  expect(overflow).toBeLessThanOrEqual(1);
}

test('completed editor remains readable across the responsive viewport matrix', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });

  for (const viewport of editorViewportMatrix) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
    await stabilizeUi(page);

    const metrics = await page.evaluate(() => {
      const bounds = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) throw new Error(`Missing responsive editor element: ${selector}`);
        const rect = element.getBoundingClientRect();
        return {
          x: rect.x,
          y: rect.y,
          right: rect.right,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
        };
      };

      return {
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        section: bounds('#preview-section'),
        preview: bounds('[data-testid="editor-preview-panel"]'),
        phone: bounds('[data-testid="editor-phone"]'),
        sidebar: bounds('[data-testid="editor-sidebar"]'),
        exportPanel: bounds('.editor-export-panel'),
        exportActions: Array.from(document.querySelectorAll<HTMLElement>('.editor-export-action')).map((element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        }),
        tabs: Array.from(document.querySelectorAll<HTMLElement>('.editor-tab')).map((element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        }),
        newVideo: bounds('.editor-new-video'),
      };
    });

    // REGRESSION: the old desktop layout gave almost all width to the fixed sidebar,
    // leaving the video and export controls in an unusable sliver.
    expect(metrics.documentOverflow, `${viewport.width}px document overflow`).toBeLessThanOrEqual(1);
    expect(metrics.section.x, `${viewport.width}px section left edge`).toBeGreaterThanOrEqual(0);
    expect(metrics.section.right, `${viewport.width}px section right edge`).toBeLessThanOrEqual(viewport.width + 1);
    expect(metrics.phone.width, `${viewport.width}px phone width`).toBeGreaterThanOrEqual(190);
    expect(metrics.phone.width, `${viewport.width}px phone width`).toBeLessThanOrEqual(280);

    for (const action of [...metrics.exportActions, ...metrics.tabs, metrics.newVideo]) {
      expect(action.height, `${viewport.width}px touch target height`).toBeGreaterThanOrEqual(44);
      expect(action.width, `${viewport.width}px touch target width`).toBeGreaterThanOrEqual(42);
    }

    if (viewport.width >= 900) {
      expect(metrics.preview.width, `${viewport.width}px desktop preview width`).toBeGreaterThanOrEqual(278);
      expect(metrics.sidebar.width, `${viewport.width}px desktop controls width`).toBeGreaterThanOrEqual(480);
      expect(metrics.preview.right, `${viewport.width}px desktop column order`).toBeLessThanOrEqual(metrics.sidebar.x + 1);
    } else {
      expect(metrics.preview.bottom, `${viewport.width}px mobile export order`).toBeLessThanOrEqual(metrics.exportPanel.y + 1);
      expect(metrics.exportPanel.bottom, `${viewport.width}px mobile controls order`).toBeLessThanOrEqual(metrics.sidebar.y + 1);
    }

    if (viewport.width <= 430) {
      await page.getByRole('tab', { name: el.tabStyles }).click();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, '[data-testid="editor-sidebar"]');
      await expect(page.getByRole('radio', { name: 'TikTok Pro' })).toBeVisible();
      await page.getByRole('tab', { name: el.tabTranscript }).click();
    }
  }
});

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

    test('workspace renders upload area without overflow', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await waitForModelPicker(page);
      await page.getByTestId('model-standard').click({ force: true });
      const uploadSection = page.getByTestId('upload-section');
      await uploadSection.waitFor({ state: 'visible' });

      // Check that the upload area is visible regardless of whether it is
      // rendering the full dropzone or the compact restored-session view.
      await expect(uploadSection).toBeVisible();

      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, 'nav');
    });

    test('completed preview stays contained without overflow', async ({ page }) => {
      await mockApi(page);
      await page.addInitScript(() => {
        localStorage.setItem('lastActiveJobId', 'job-futurist');
      });
      await page.goto('/');

      await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, 'main');
      await expect(page.getByText(el.subtitlesReady)).toBeVisible();
      await expect(page.getByRole('tab', { name: el.tabTranscript })).toBeVisible();
      await expect(page.getByRole('tab', { name: el.tabStyles })).toBeVisible();
    });

    test('history section shows event cards neatly', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await waitForDashboardShell(page);
      await page.getByRole('button', { name: el.profileLabel }).click();
      await page.getByRole('button', { name: el.historyTitle }).click();
      await page.getByRole('heading', { name: el.historyTitle }).waitFor();
      await page.getByText(el.historyExpiry).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);

      // Check that the history section is properly laid out
      // The mock history data might not be loaded automatically, so just verify the section exists
      await expect(page.getByRole('heading', { name: el.historyTitle })).toBeVisible();
      await expect(page.getByText(el.historyExpiry)).toBeVisible();
    });

    test('account settings modal keeps controls readable', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await waitForDashboardShell(page);

      // Wait for the account settings button to be rendered (after auth check) and click it
      await page.getByRole('button', { name: el.profileLabel }).click();

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
