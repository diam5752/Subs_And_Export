import { expect, test } from '@playwright/test';
import el from '@/i18n/el.json';
import { mockApi } from './mocks';

test('gsubs branding is visible across the public shell and metadata', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');

  const header = page.getByRole('banner', { name: 'gsubs studio' });
  const headerLogo = header.getByRole('img', { name: 'gsubs' });
  await expect(headerLogo).toBeVisible();
  await expect(headerLogo).toHaveAttribute('src', '/brand/gsubs-logo-light.svg');
  const footerLogo = page.locator('.footer-brand img');
  await expect(footerLogo).toBeVisible();
  await expect(footerLogo).toHaveCSS('width', '88px');
  await expect(page).toHaveTitle('gsubs · Subtitle Studio');

  const manifestResponse = await page.request.get('/manifest.webmanifest');
  expect(manifestResponse.ok()).toBe(true);
  const manifest = await manifestResponse.json();
  expect(manifest).toMatchObject({
    name: 'gsubs · Subtitle Studio',
    short_name: 'gsubs',
  });

  for (const asset of [
    '/brand/gsubs-logo-light.svg',
    '/brand/gsubs-logo-dark.svg',
    '/brand/gsubs-mark.svg',
    '/gsubs-watermark.png',
    '/icon.png',
    '/apple-icon.png',
  ]) {
    const response = await page.request.get(asset);
    expect(response.ok(), asset).toBe(true);
    expect(Number(response.headers()['content-length'] ?? 1), asset).toBeGreaterThan(0);
  }
});

test('gsubs identity remains visible on auth and legal routes', async ({ page }) => {
  await mockApi(page, { authenticated: false });

  for (const route of ['/login', '/register', '/privacy', '/terms']) {
    await page.goto(route);
    await expect(page.getByRole('img', { name: 'gsubs' }).first()).toBeVisible();
    await expect(page.getByRole('img', { name: 'gsubs' }).first())
      .toHaveAttribute('src', '/brand/gsubs-logo-light.svg');
  }
});

test('the editor preview uses the selected gsubs watermark', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });

  await page.goto('/');
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
  await page.getByRole('tab', { name: el.tabStyles }).click();
  await page.getByRole('switch', { name: el.watermarkLabel }).click();

  const watermark = page.getByRole('img', { name: 'gsubs watermark' });
  await expect(watermark).toBeVisible();
  await expect(watermark).toHaveAttribute(
    'src',
    /\/_next\/image\?url=%2Fgsubs-watermark\.png/,
  );
});
