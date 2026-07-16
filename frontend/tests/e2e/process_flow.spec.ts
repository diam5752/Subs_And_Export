
import { test, expect } from '@playwright/test';
import { mockApi, waitForModelPicker } from './mocks';
import el from '@/i18n/el.json';

test.describe('Video Processing Flow', () => {
    test('complete flow: upload -> processing -> completed -> download', async ({ page }) => {
        // 1. Mock API with specific job sequence
        await mockApi(page);
        const exportPayloads: Array<Record<string, unknown>> = [];

        // Override job creation to return a specific ID
        await page.route('**/videos/process', async route => {
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
        await waitForModelPicker(page);

        // Select model first
        await page.getByTestId('model-standard').click({ force: true });

        // Check if we are stuck on loading
        await expect(page.getByText(el.loading)).not.toBeVisible();
        // Check if we are stuck on login
        await expect(page.getByText(el.loginHeading)).not.toBeVisible();

        // 3. Upload File
        // Find hidden input
        const fileInput = page.locator('input[type="file"]');
        await fileInput.setInputFiles({
            name: 'test.mp4',
            mimeType: 'video/mp4',
            buffer: Buffer.from('dummy content')
        });
        // Trigger change event to ensure React picks it up
        await fileInput.dispatchEvent('change');

        // 4. Verify customization step appears (if setup requires it) 
        // OR if upload starts immediately. 
        // The current UI might show settings first?
        // Actually, dropzone usually uploads immediately OR requires button?
        // "Review Video Settings" button?
        // Let's check ProcessView logic in mind -> Upload -> Settings -> Start.

        // Wait for "Review Video Settings" or similar trigger if needed.
        // If the mock flow assumes Upload -> Auto Start, then we check for progress.
        // If Upload -> Settings -> Click Process, we must click.
        // Based on previous `ProcessView.test.tsx`, it seems we select file, then change settings, then click "Process Video".

        // Wait for the uploaded file heading to appear to confirm upload.
        await expect(page.getByRole('heading', { name: 'test.mp4' })).toBeVisible();

        // Check if button is enabled/visible
        const processBtn = page.getByRole('button', { name: /Έναρξη|Start/i });
        await expect(processBtn).toBeVisible();
        await processBtn.click({ force: true });

        // 5. Verify Progress Mode
        // Assuming el.progressLabel or just text regex
        await expect(
            page.getByRole('progressbar', { name: /Processing...|Επεξεργασία.../ }),
        ).toBeVisible();

        // 6. Wait for Completion
        // Poll mock should switch to completed eventually.
        // Once completed, the SRT export button should appear in PreviewSection
        await expect(page.getByTestId('srt-btn')).toBeVisible({ timeout: 25000 });

        // 7. Check Download Options
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
});
