
import { test, expect } from '@playwright/test';
import { mockApi } from './mocks';
import el from '@/i18n/el.json';

test.describe('Video Processing Flow', () => {
    test('complete flow: upload -> processing -> completed -> download', async ({ page }) => {
        // 1. Mock API with specific job sequence
        await mockApi(page);

        // Override job creation to return a specific ID
        await page.route('**/api/videos/process', async route => {
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
        await page.route('**/api/videos/jobs/job-123', async route => {
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
                    output_size: 1024
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

        // 2. Go to page
        await page.goto('/');

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

        // Wait for text "test.mp4" to appear to confirm upload
        await expect(page.getByText('test.mp4')).toBeVisible();

        // Check if button is enabled/visible
        const processBtn = page.getByRole('button', { name: /Έναρξη|Start/i });
        await expect(processBtn).toBeVisible();
        await processBtn.click({ force: true });

        // 5. Verify Progress Mode
        // Assuming el.progressLabel or just text regex
        await expect(page.getByText(/Processing...|Επεξεργασία.../)).toBeVisible();

        // 6. Wait for Completion
        // Poll mock should switch to completed eventually.
        // Once completed, the SRT export button should appear in PreviewSection
        await expect(page.getByTestId('srt-btn')).toBeVisible({ timeout: 25000 });

        // 7. Check Download Options
        await expect(page.getByTestId('download-1080p-btn')).toBeVisible();
    });
});
