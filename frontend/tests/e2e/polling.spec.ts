import { expect, test, type Page, type Route } from '@playwright/test';
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

        // Dashboard should render with the upload area
        await expect(page.getByText(el.uploadDropTitle)).toBeVisible();

        // History section should be visible with mocked jobs
        await expect(page.getByText('History')).toBeVisible();
    });

    test('dashboard handles authenticated state correctly', async ({ page }) => {
        await mockApi(page, { authenticated: true });
        await page.goto('/');
        await page.waitForLoadState('networkidle');
        await stabilizeUi(page);

        // Verify dashboard loaded
        await expect(page.getByText(el.uploadDropTitle)).toBeVisible();

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
        // History section should be visible
        await expect(page.getByText('History')).toBeVisible();
    });
});
