import { expect, test, type Page } from '@playwright/test';
import el from '@/i18n/el.json';
import { mockApi, stabilizeUi, waitForUploadWorkspace } from './mocks';

async function expectDialogContained(page: Page): Promise<void> {
  const metrics = await page.getByTestId('credit-purchase-dialog').evaluate((dialog) => {
    const panel = dialog.firstElementChild as HTMLElement | null;
    if (!panel) throw new Error('Missing credit purchase panel');
    const rect = panel.getBoundingClientRect();
    return {
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });

  expect(metrics.left).toBeGreaterThanOrEqual(0);
  expect(metrics.top).toBeGreaterThanOrEqual(0);
  expect(metrics.right).toBeLessThanOrEqual(await page.evaluate(() => window.innerWidth));
  expect(metrics.bottom).toBeLessThanOrEqual(await page.evaluate(() => window.innerHeight));
  expect(metrics.documentOverflow).toBeLessThanOrEqual(1);
}

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`credit wallet and packages stay usable on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mockApi(page);
    await page.goto('/');
    await waitForUploadWorkspace(page);

    await page.getByTestId('credits-balance').click();
    const dialog = page.getByRole('dialog', { name: el.creditPurchaseTitle });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText(el.creditPurchaseTotalBalance)).toBeVisible();
    await expect(dialog.getByText(el.creditPurchaseCloudBalance)).toBeVisible();
    await expect(dialog.getByText(el.creditPurchasePromoBalance)).toBeVisible();
    await expect(dialog.getByRole('radio')).toHaveCount(3);
    await expect(dialog.getByRole('radio', { name: /Starter/ })).toContainText('€1.00');
    await expect(dialog.getByRole('radio', { name: /Creator/ })).toContainText('€3.00');
    await expect(dialog.getByRole('radio', { name: /Studio/ })).toContainText('€10.00');
    await expect(dialog.getByText(el.creditPurchasePopular)).toBeVisible();

    const payButton = dialog.getByRole('button', { name: /Πληρωμή/ });
    await expect(payButton).toBeDisabled();
    await stabilizeUi(page);
    await expectDialogContained(page);
  });
}

test('checkout posts one package with an idempotency key before Stripe redirect', async ({ page }) => {
  await mockApi(page);
  await page.route('https://checkout.stripe.com/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<!doctype html><title>Stripe test checkout</title><h1>Stripe test checkout</h1>',
    });
  });
  await page.goto('/');
  await waitForUploadWorkspace(page);
  await page.getByTestId('credits-balance').click();

  const dialog = page.getByRole('dialog', { name: el.creditPurchaseTitle });
  await dialog.getByRole('radio', { name: /Creator/ }).click();
  await dialog.getByRole('checkbox').check();

  const requestPromise = page.waitForRequest((request) => (
    request.method() === 'POST' && request.url().endsWith('/billing/checkout')
  ));
  await dialog.getByRole('button', { name: 'Πληρωμή €3.00' }).click();
  const request = await requestPromise;

  expect(request.postDataJSON()).toEqual({ package_key: 'core' });
  expect(request.headers()['idempotency-key']).toMatch(/^checkout-.{16,}$/);
  await expect(page).toHaveURL('https://checkout.stripe.com/c/pay/cs_test_subframe');
  await expect(page.getByRole('heading', { name: 'Stripe test checkout' })).toBeVisible();
});
