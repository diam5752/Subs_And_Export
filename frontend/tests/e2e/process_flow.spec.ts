
import { test, expect } from '@playwright/test';
import { resolve } from 'node:path';
import { mockApi, waitForUploadWorkspace } from './mocks';
import el from '@/i18n/el.json';

test.describe('Video Processing Flow', () => {
    test('complete flow: upload -> processing -> completed -> download', async ({ page }) => {
        // 1. Mock API with specific job sequence
        await mockApi(page);
        const exportPayloads: Array<Record<string, unknown>> = [];

        // Override job creation to return a specific ID
        let processRequests = 0;
        await page.route('**/videos/process', async route => {
            processRequests += 1;
            const json = {
                id: 'job-123',
                status: 'pending',
                user_id: 'test-user',
                created_at: Date.now(),
                updated_at: Date.now(),
                progress: 0,
                message: 'Queued',
                result_data: {}
            };
            await route.fulfill({ json });
        });

        // Mock polling for job-123
        let pollCount = 0;
        await page.route('**/videos/jobs/job-123', async route => {
            pollCount++;
            let status = 'processing';
            let progress = 10;
            let result_data = {};

            if (pollCount > 1) { status = 'processing'; progress = 70; }
            if (pollCount > 2) {
                status = 'completed';
                progress = 100;
                result_data = {
                    public_url: '/static/video.mp4',
                    artifact_url: '/static/artifacts',
                    output_size: 1024,
                    model_size: 'standard',
                    transcribe_provider: 'groq'
                };
            }

            await route.fulfill({
                json: {
                    id: 'job-123',
                    status,
                    user_id: 'test-user',
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    progress,
                    message: status === 'completed' ? 'Done' : 'Processing...',
                    result_data
                }
            });
        });

        await page.route('**/videos/jobs/job-123/export', async route => {
            const payload = route.request().postDataJSON() as Record<string, unknown>;
            exportPayloads.push(payload);
            const resolution = String(payload.resolution);
            const extension = ['srt', 'vtt', 'txt'].includes(resolution) ? resolution : 'mp4';
            await route.fulfill({
                json: {
                    id: 'job-123',
                    status: 'completed',
                    user_id: 'test-user',
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    progress: 100,
                    message: 'Done',
                    result_data: {
                        public_url: '/static/video.mp4',
                        artifact_url: '/static/artifacts',
                        output_size: 1024,
                        model_size: 'standard',
                        transcribe_provider: 'groq',
                        variants: {
                            [resolution]: `/static/artifacts/job-123/processed_${resolution}.${extension}`,
                        },
                    },
                },
            });
        });

        // 2. Go to page
        await page.goto('/');
        await waitForUploadWorkspace(page);

        // Check if we are stuck on loading
        await expect(page.getByText(el.loading)).not.toBeVisible();
        // Check if we are stuck on login
        await expect(page.getByText(el.loginHeading)).not.toBeVisible();

        // 3. Upload a real 8.6s vertical MP4. Upload and configuration remain
        // free of side effects until the user explicitly confirms the coin cost.
        const fileInput = page.locator('input[type="file"]');
        await fileInput.setInputFiles(
            resolve(process.cwd(), '../backend/tests/data/demo_output.mp4'),
        );
        await expect(page.getByRole('heading', { name: 'demo_output.mp4' })).toBeVisible();
        expect(processRequests).toBe(0);

        await page.getByRole('button', { name: el.startProcessing }).click();
        await expect(page.getByRole('dialog', { name: el.processingGateCostTitle })).toBeVisible();
        expect(processRequests).toBe(0);

        const processRequest = page.waitForRequest(
            request => request.method() === 'POST' && request.url().endsWith('/videos/process'),
        );
        await page.getByRole('button', { name: el.processingGateConfirm.replace('{cost}', '25') }).click();
        await processRequest;

        // 4. Wait for completion. The mock job may finish before the transient
        // progress bar can be observed on fast local machines.
        // Once completed, the SRT export button should appear in PreviewSection
        await expect(page.getByTestId('srt-btn')).toBeVisible({ timeout: 25000 });
        expect(pollCount).toBeGreaterThanOrEqual(3);

        // 5. Check Download Options
        await expect(page.getByTestId('download-1080p-btn')).toBeVisible();

        const srtDownloadPromise = page.waitForEvent('download');
        await page.getByTestId('srt-btn').click();
        const srtDownload = await srtDownloadPromise;
        expect(srtDownload.suggestedFilename()).toContain('processed_srt.srt');

        const mp4DownloadPromise = page.waitForEvent('download');
        await page.getByTestId('download-1080p-btn').click();
        const mp4Download = await mp4DownloadPromise;
        expect(mp4Download.suggestedFilename()).toContain('processed_1080x1920.mp4');

        expect(exportPayloads).toEqual([
            expect.objectContaining({
                resolution: 'srt',
                max_subtitle_lines: 2,
                subtitle_size: 85,
                highlight_style: 'active-graphics',
                karaoke_enabled: true,
            }),
            expect.objectContaining({
                resolution: '1080x1920',
                max_subtitle_lines: 2,
                subtitle_size: 85,
                highlight_style: 'active-graphics',
                karaoke_enabled: true,
            }),
        ]);
    });

    test('guest keeps the uploaded file through login and sees cost before start', async ({ page }) => {
        await mockApi(page, { authenticated: false });
        let processRequests = 0;
        await page.route('**/videos/process', async route => {
            processRequests += 1;
            await route.fulfill({
                json: {
                    id: 'job-guest',
                    status: 'pending',
                    user_id: 'user-demo-1',
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    progress: 0,
                    message: 'Queued',
                    result_data: {},
                },
            });
        });

        await page.goto('/');
        await waitForUploadWorkspace(page, { authenticated: false });
        await page.locator('input[type="file"]').setInputFiles(
            resolve(process.cwd(), '../backend/tests/data/demo_output.mp4'),
        );

        await expect(page).toHaveURL(/\/$/);
        await expect(page.getByRole('heading', { name: 'demo_output.mp4' })).toBeVisible();
        expect(processRequests).toBe(0);

        await page.getByRole('button', { name: el.startProcessing }).click();
        await expect(page.getByRole('dialog', { name: el.processingGateAuthTitle })).toBeVisible();
        expect(processRequests).toBe(0);

        await page.getByLabel(el.loginEmailLabel).fill('guest@example.com');
        await page.getByLabel(el.loginPasswordLabel).fill('correct horse battery staple');
        await page.getByRole('button', { name: el.processingGateLoginSubmit }).click();

        await expect(page.getByRole('dialog', { name: el.processingGateCostTitle })).toBeVisible();
        await expect(
            page.locator('[data-testid="upload-section"] h4', { hasText: 'demo_output.mp4' }),
        ).toBeVisible();
        expect(processRequests).toBe(0);

        const processRequest = page.waitForRequest(
            request => request.method() === 'POST' && request.url().endsWith('/videos/process'),
        );
        await page.getByRole('button', { name: el.processingGateConfirm.replace('{cost}', '25') }).click();
        await processRequest;
        expect(processRequests).toBe(1);
    });
});
