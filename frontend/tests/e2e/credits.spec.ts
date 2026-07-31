import { expect, test } from '@playwright/test';
import el from '@/i18n/el.json';
import { mockApi, waitForUploadWorkspace } from './mocks';

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`approved paid-credit UI opens the purchase dialog on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mockApi(page);
    await page.goto('/');
    await waitForUploadWorkspace(page);

    const balance = page.getByTestId('credits-balance');
    await expect(balance).toBeVisible();
    await expect(balance).toContainText('125');
    await expect(balance).toContainText('+');

    await balance.click();

    const dialog = page.getByRole('dialog', {
      name: el.creditPurchaseTitle,
    });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('€1.00', { exact: true })).toBeVisible();
    await expect(dialog.getByText('€3.00', { exact: true })).toBeVisible();
    await expect(dialog.getByText('€10.00', { exact: true })).toBeVisible();
    await expect(dialog.getByText('Ascentia G.P.')).toBeVisible();
    await expect(dialog.getByRole('button', {
      name: /€1\.00/,
    })).toBeDisabled();
  });
}

test('approved terms expose seller, payment, refund and withdrawal wording', async ({ page }) => {
  await page.goto('/terms');

  await expect(page.getByRole('heading', {
    name: el.termsSellerTitle,
  })).toBeVisible();
  await expect(page.getByText(el.termsSellerBody)).toBeVisible();
  await expect(page.getByRole('heading', {
    name: el.termsPaidCreditsScopeTitle,
  })).toBeVisible();
  await expect(page.getByText(el.termsRefundsBody)).toBeVisible();
  await expect(page.getByText(el.termsWithdrawalFormBody)).toBeVisible();
  await expect(page.locator('#withdrawal')).toHaveCount(1);
});
