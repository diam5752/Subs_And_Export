import { expect, test } from '@playwright/test';
import el from '@/i18n/el.json';
import { mockApi, waitForUploadWorkspace } from './mocks';

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`disabled paid-credit UI keeps only the wallet visible on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mockApi(page);
    await page.goto('/');
    await waitForUploadWorkspace(page);

    const balance = page.getByTestId('credits-balance');
    await expect(balance).toBeVisible();
    await expect(balance).toContainText('125');
    await expect(balance).not.toContainText('+');

    await balance.click();

    await expect(page.getByRole('dialog', {
      name: el.creditPurchaseTitle,
    })).toHaveCount(0);
    await expect(page.getByRole('button', {
      name: el.processingGateBuyCredits,
    })).toHaveCount(0);
    await expect(page.getByText(/€(?:1|3|10)\.00/)).toHaveCount(0);
    await expect(page.getByText(el.creditPurchasePay, { exact: false })).toHaveCount(0);
  });
}

test('inactive terms expose only the placeholder and no draft operative wording', async ({ page }) => {
  await page.goto('/terms');

  await expect(page.getByRole('heading', {
    name: el.termsPaidCreditsDraftTitle,
  })).toBeVisible();
  await expect(page.getByText(el.termsPaidCreditsDraftBody)).toBeVisible();
  await expect(page.getByText(
    /προπληρωμένες εσωτερικές μονάδες|αναλογικό ποσό|Προς Ascentia \/ GSUBS/,
  )).toHaveCount(0);
  await expect(page.locator('#withdrawal')).toHaveCount(0);
});
