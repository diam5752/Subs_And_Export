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

test('cancelled checkout notice clears only its return parameters', async ({ page }) => {
  await mockApi(page);

  await page.goto('/?checkout=cancelled&session_id=cs_test_cancelled&campaign=beta#credits');
  await waitForUploadWorkspace(page);

  await expect(page.getByRole('status')).toContainText(el.creditPurchaseCancelled);
  await expect.poll(() => new URL(page.url()).search).toBe('?campaign=beta');
  expect(new URL(page.url()).hash).toBe('#credits');
});

test('checkout return keeps its session until a pending payment becomes paid', async ({ page }) => {
  const sessionId = 'cs_test_pending_then_paid';
  let statusChecks = 0;
  await mockApi(page);
  await page.route(`**/billing/checkout/${sessionId}`, async (route) => {
    statusChecks += 1;
    const paid = statusChecks > 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        purchase_id: 'purchase-delayed',
        package_key: 'starter',
        credits: 100,
        amount_eur_cents: 100,
        status: paid ? 'paid' : 'awaiting_payment',
        checkout_session_id: sessionId,
        wallet: {
          balance: paid ? 225 : 125,
          paid_balance: paid ? 200 : 100,
          promotional_balance: 25,
          reversal_debt: 0,
          ai_spendable_balance: paid ? 200 : 100,
        },
      }),
    });
  });

  await page.goto(`/?checkout=success&session_id=${sessionId}`);
  await waitForUploadWorkspace(page);

  await expect(page.getByRole('status')).toContainText(el.creditPurchasePending);
  expect(new URL(page.url()).searchParams.get('session_id')).toBe(sessionId);

  await expect(page.getByRole('status')).toContainText(
    el.creditPurchaseSuccess.replace('{count}', '100'),
  );
  await expect(page.getByTestId('credits-balance')).toContainText('225');
  await expect.poll(() => new URL(page.url()).search).toBe('');
  expect(statusChecks).toBe(2);
});

test('checkout return preserves retry context after a status error', async ({ page }) => {
  const sessionId = 'cs_test_retry_after_error';
  let statusChecks = 0;
  await mockApi(page);
  await page.route(`**/billing/checkout/${sessionId}`, async (route) => {
    statusChecks += 1;
    if (statusChecks === 1) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Temporary reconciliation error' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        purchase_id: 'purchase-retry',
        package_key: 'starter',
        credits: 100,
        amount_eur_cents: 100,
        status: 'paid',
        checkout_session_id: sessionId,
        wallet: {
          balance: 225,
          paid_balance: 200,
          promotional_balance: 25,
          reversal_debt: 0,
          ai_spendable_balance: 200,
        },
      }),
    });
  });

  await page.goto(`/?checkout=success&session_id=${sessionId}`);
  await waitForUploadWorkspace(page);

  const retry = page.getByRole('button', { name: el.creditPurchaseRetry });
  await expect(retry).toBeVisible();
  expect(new URL(page.url()).searchParams.get('session_id')).toBe(sessionId);

  await retry.click();

  await expect(page.getByRole('status')).toContainText(
    el.creditPurchaseSuccess.replace('{count}', '100'),
  );
  await expect(page.getByTestId('credits-balance')).toContainText('225');
  await expect.poll(() => new URL(page.url()).search).toBe('');
  expect(statusChecks).toBe(2);
});
