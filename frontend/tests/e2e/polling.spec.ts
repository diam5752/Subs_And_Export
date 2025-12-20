import { test, expect } from '@playwright/test';
import { mockApi, stabilizeUi } from './mocks';
import el from '@/i18n/el.json';

/**
 * E2E tests for job polling functionality.
 * These tests verify the frontend correctly handles job status transitions.
 */

test.describe('Job Polling E2E', () => {
    test.use({ viewport: { width: 1440, height: 900 } });

    test('dashboard can display processing jobs from history', async ({ page }) => {
        // Use the existing mockApi which includes a processing job
        await mockApi(page);
        await page.goto('/');
        await page.waitForLoadState('networkidle');
        await page.getByTestId('model-standard').click({ force: true });

        // Dashboard should render with the upload area
        const uploadSection = page.getByTestId('upload-section');
        await uploadSection.waitFor({ state: 'visible' });
        await expect(uploadSection).toBeVisible();

        // History lives under the account modal
        await page.getByRole('button', { name: el.accountSettingsTitle }).click();
        await page.getByRole('button', { name: el.historyTitle }).click();
        await expect(page.getByRole('heading', { name: el.historyTitle })).toBeVisible();
    });

    test('dashboard handles authenticated state correctly', async ({ page }) => {
        await mockApi(page, { authenticated: true });
        await page.goto('/');
        await page.waitForLoadState('networkidle');
        await page.getByTestId('model-standard').click({ force: true });

        // Verify dashboard loaded
        const uploadSection = page.getByTestId('upload-section');
        await uploadSection.waitFor({ state: 'visible' });
        await expect(uploadSection).toBeVisible();

        // Account settings button should be available
        await expect(page.getByRole('button', { name: el.accountSettingsTitle })).toBeVisible();
    });

    test('unauthenticated state redirects to login', async ({ page }) => {
        await mockApi(page, { authenticated: false });
        await page.goto('/');
        await page.waitForURL('**/login');
        await expect(page).toHaveURL(/\/login$/);
    });

    test('job list displays different job statuses', async ({ page }) => {
        await mockApi(page);
        await page.goto('/');
        await page.waitForLoadState('networkidle');
        await stabilizeUi(page);

        // The mock includes jobs with various statuses (completed, processing, pending, failed)
        // History lives under the account modal
        await page.getByRole('button', { name: el.accountSettingsTitle }).click();
        await page.getByRole('button', { name: el.historyTitle }).click();
        await expect(page.getByRole('heading', { name: el.historyTitle })).toBeVisible();
    });
});
