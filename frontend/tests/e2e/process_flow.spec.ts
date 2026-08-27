
import { test, expect } from '@playwright/test';
import { resolve } from 'node:path';
import { mockApi, waitForUploadWorkspace } from './mocks';
import el from '@/i18n/el.json';

test.describe('Video Processing Flow', () => {
    test('mock processing accepts promotional credits without claiming a provider call', async ({ page }) => {
        // REGRESSION: the mock route read only ai_spendable_balance and blocked
        // users whose local promotional balance fully covered the job.
        await mockApi(page);
        await page.route('**/auth/points', async route => {
            await route.fulfill({
                json: {
                    balance: 100,
                    paid_balance: 0,
                    promotional_balance: 100,
                    reversal_debt: 0,
                    ai_spendable_balance: 0,
                },
            });
        });

        await page.goto('/');
        await waitForUploadWorkspace(page);
        await page.locator('input[type="file"]').setInputFiles(
            resolve(process.cwd(), '../backend/tests/data/demo_output.mp4'),
        );
        await page.getByRole('button', {
            name: new RegExp(el.startProcessing),
        }).click();

        const costDialog = page.getByRole('dialog', {
            name: el.processingGateCostTitle,
        });
        await expect(costDialog).toBeVisible();
        await expect(costDialog.getByText(el.processingGateTotalBalanceLabel)).toBeVisible();
        await expect(costDialog.getByText(el.processingGateLocalChargeNote)).toBeVisible();
        await expect(costDialog.getByText(el.processingGateBalanceLabel)).toHaveCount(0);
        await expect(costDialog.getByRole('button', {
            name: new RegExp(el.processingGateConfirm.replace('{cost}', '\\d+')),
        })).toBeEnabled();
    });

    test('authoritative 30-to-60 quote change requires a second explicit confirmation', async ({ page }) => {
        // REGRESSION: the browser must not silently retry when server-measured
        // duration crosses a pricing boundary after the first confirmation.
        await mockApi(page);
        const processMetadata: Array<Record<string, unknown>> = [];
        let processRequests = 0;
        await page.route('**/videos/process*', async route => {
            processRequests += 1;
            const encodedMetadata = route.request().headers()['x-gsubs-upload-metadata'];
            processMetadata.push(JSON.parse(
                Buffer.from(encodedMetadata, 'base64').toString('utf8'),
            ) as Record<string, unknown>);
            if (processRequests === 1) {
                await route.fulfill({
                    status: 409,
                    json: {
                        detail: 'Processing quote changed',
                        code: 'PROCESSING_QUOTE_CHANGED',
                        details: {
                            duration_seconds: 180.001,
                            required_credits: 60,
                        },
                    },
                });
                return;
            }
            await route.fulfill({
                json: {
                    id: 'job-quote-confirmed',
                    status: 'pending',
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    progress: 0,
                    message: 'Queued',
                    result_data: {},
                },
            });
        });

        await page.goto('/');
        await waitForUploadWorkspace(page);
        await page.locator('input[type="file"]').setInputFiles(
            resolve(process.cwd(), '../backend/tests/data/demo_output.mp4'),
        );
        await page.getByRole('button', {
            name: new RegExp(el.startProcessing),
        }).click();

        const costDialog = page.getByRole('dialog', {
            name: el.processingGateCostTitle,
        });
        await costDialog.getByRole('button', {
            name: new RegExp(el.processingGateConfirm.replace('{cost}', '30')),
        }).click();

        await expect(costDialog).toBeVisible();
        await expect(costDialog.getByText('60', { exact: true })).toBeVisible();
        await expect(costDialog.getByRole('alert')).toContainText('180.001');
        await expect(costDialog.getByRole('alert')).toContainText('60');
        await expect(page.locator('[data-testid="upload-section"] h4')).toHaveText(
            'demo_output.mp4',
        );
        expect(processRequests).toBe(1);
        expect(processMetadata[0]).toEqual(expect.objectContaining({
            authorized_credits: 30,
            filename: 'demo_output.mp4',
        }));

        await page.waitForTimeout(250);
        expect(processRequests).toBe(1);

        await costDialog.getByRole('button', {
            name: new RegExp(el.processingGateConfirm.replace('{cost}', '60')),
        }).click();
        await expect.poll(() => processRequests).toBe(2);
        expect(processMetadata[1]).toEqual(expect.objectContaining({
            authorized_credits: 60,
            filename: 'demo_output.mp4',
        }));
        const { authorized_credits: firstCredits, ...firstSettings } = processMetadata[0];
        const { authorized_credits: secondCredits, ...secondSettings } = processMetadata[1];
        expect(firstCredits).toBe(30);
        expect(secondCredits).toBe(60);
        expect(secondSettings).toEqual(firstSettings);
        await page.waitForTimeout(250);
        expect(processRequests).toBe(2);
    });

    test('complete flow: upload -> processing -> completed -> download', async ({ page }) => {
        // 1. Mock API with specific job sequence
        await mockApi(page);
        const exportPayloads: Array<Record<string, unknown>> = [];
        const exportedPreviewRequests: URL[] = [];
        page.on('request', (request) => {
            const url = new URL(request.url());
            if (
                url.pathname.endsWith('/static/artifacts/job-123/processed_720x1280.mp4')
                && url.searchParams.get('download') !== 'true'
                && !url.searchParams.has('grant')
            ) {
                exportedPreviewRequests.push(url);
            }
        });

        // Override job creation to return a specific ID
        let processRequests = 0;
        await page.route('**/videos/process*', async route => {
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
                    original_filename: 'demo_output.mp4',
                    output_size: 1024,
                    transcribe_tier: 'standard',
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
                        original_filename: 'demo_output.mp4',
                        output_size: 1024,
                        transcribe_tier: 'standard',
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

        const startButton = page.getByRole('button', { name: new RegExp(el.startProcessing) });
        expect((await startButton.innerText()).match(/([\d,.]+)\s*$/)?.[1]).toBeTruthy();
        await startButton.click();
        const costDialog = page.getByRole('dialog', { name: el.processingGateCostTitle });
        await expect(costDialog).toBeVisible();
        expect(processRequests).toBe(0);

        const processRequest = page.waitForRequest(
            request => request.method() === 'POST'
                && /\/videos\/process(?:-stream)?$/.test(request.url()),
        );
        await costDialog.getByRole('button', {
            name: new RegExp(el.processingGateConfirm.replace('{cost}', '\\d+')),
        }).click();
        await processRequest;

        // 4. Wait for completion. The mock job may finish before the transient
        // progress bar can be observed on fast local machines.
        // Once completed, the compact export trigger should appear in PreviewSection.
        const exportButton = page.getByRole('button', { name: el.exportMenuButton, exact: true });
        await expect(exportButton).toBeVisible({ timeout: 25000 });
        expect(pollCount).toBeGreaterThanOrEqual(3);

        await page.setViewportSize({ width: 390, height: 844 });
        const phone = page.getByTestId('editor-phone');
        const previewVideo = phone.locator('video');
        expect(await previewVideo.getAttribute('controls')).toBeNull();
        await expect(page.getByTestId('editor-preview-controls')).toHaveCount(0);
        await expect(page.locator('.subtitle-edit-affordance')).toHaveCount(0);
        await expect(page.getByTestId('subtitle-touch-manipulation-hint')).toHaveCount(0);
        const phoneBox = await phone.boundingBox();
        expect(phoneBox).not.toBeNull();
        expect(await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
        )).toBe(true);

        // 5. Check Download Options
        await exportButton.click();
        await expect(page.getByTestId('download-720p-btn')).toBeVisible();
        await expect(page.getByTestId('download-1080p-btn')).toBeVisible();
        await expect(page.getByTestId('vtt-btn')).toHaveCount(0);

        const srtDownloadPromise = page.waitForEvent('download');
        await page.getByTestId('srt-btn').click();
        const srtDownload = await srtDownloadPromise;
        expect(srtDownload.suggestedFilename()).toBe('demo_output_subs.srt');

        await exportButton.click();
        const mp4DownloadPromise = page.waitForEvent('download');
        await page.getByTestId('download-720p-btn').click();
        const mp4Download = await mp4DownloadPromise;
        expect(mp4Download.suggestedFilename()).toBe('demo_output_subs.mp4');
        // REGRESSION: switching the preview to the exported MP4 while starting
        // its download issued two full private-media requests for one click.
        await page.waitForTimeout(500);
        expect(exportedPreviewRequests).toHaveLength(0);

        expect(exportPayloads).toEqual([
            expect.objectContaining({
                resolution: 'srt',
                max_subtitle_lines: 2,
                subtitle_size: 85,
                highlight_style: 'active-graphics',
                karaoke_enabled: true,
            }),
            expect.objectContaining({
                resolution: '720x1280',
                video_quality: 'low size',
                max_subtitle_lines: 2,
                subtitle_size: 85,
                highlight_style: 'active-graphics',
                karaoke_enabled: true,
            }),
        ]);
    });

    test('slow mobile upload uses progress-capable XHR, stays responsive, and submits once', async ({ page }) => {
        test.setTimeout(60_000);
        await mockApi(page);
        let processRequests = 0;
        await page.route('**/videos/process*', async route => {
            processRequests += 1;
            // Playwright route interception can bypass Chromium's emulated
            // upload throughput. Keep the XHR pending long enough to assert
            // the in-flight mobile UI deterministically.
            await new Promise(resolve => setTimeout(resolve, 750));
            await route.fulfill({
                json: {
                    id: 'job-slow-upload',
                    status: 'pending',
                    user_id: 'test-user',
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    progress: 0,
                    message: 'Queued',
                    result_data: {},
                },
            });
        });

        await page.setViewportSize({ width: 390, height: 844 });
        await page.goto('/');
        await waitForUploadWorkspace(page);
        await page.locator('input[type="file"]').setInputFiles(
            resolve(process.cwd(), '../backend/tests/data/demo_output.mp4'),
        );
        await page.getByRole('button', {
            name: new RegExp(el.startProcessing),
        }).click();

        const costDialog = page.getByRole('dialog', {
            name: el.processingGateCostTitle,
        });
        await expect(costDialog).toBeVisible();
        const processRequest = page.waitForRequest(
            request => request.method() === 'POST'
                && /\/videos\/process(?:-stream)?$/.test(request.url()),
        );
        const cdp = await page.context().newCDPSession(page);
        await cdp.send('Network.enable');
        await cdp.send('Network.emulateNetworkConditions', {
            offline: false,
            latency: 350,
            downloadThroughput: 512 * 1024,
            uploadThroughput: 384 * 1024,
            connectionType: 'cellular3g',
        });

        try {
            await costDialog.getByRole('button', {
                name: new RegExp(el.processingGateConfirm.replace('{cost}', '\\d+')),
            }).click();

            const progressBar = page.getByRole('progressbar');
            await expect(progressBar).toBeVisible();
            expect(await page.evaluate(
                () => document.documentElement.scrollWidth <= window.innerWidth,
            )).toBe(true);
        } finally {
            await cdp.send('Network.emulateNetworkConditions', {
                offline: false,
                latency: 0,
                downloadThroughput: -1,
                uploadThroughput: -1,
                connectionType: 'none',
            });
            await cdp.detach();
        }

        const request = await processRequest;
        // REGRESSION: fetch-based uploads could not expose browser upload
        // progress, while multipart uploads forced the server to spool and
        // copy the complete file before processing could begin.
        expect(request.resourceType()).toBe('xhr');
        expect(request.url()).toMatch(/\/videos\/process-stream$/);
        expect(request.headers()['content-type']).toContain('video/mp4');
        expect(request.headers()['x-gsubs-upload-metadata']).toBeTruthy();
        await expect.poll(() => processRequests).toBe(1);
    });

    // REGRESSION: legal navigation from inline registration replaced the page
    // and discarded the guest's selected upload.
    test('guest keeps the uploaded file through login and sees cost before start', async ({ page }) => {
        await mockApi(page, { authenticated: false });
        let processRequests = 0;
        await page.route('**/videos/process*', async route => {
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

        const startButton = page.getByRole('button', { name: new RegExp(el.startProcessing) });
        expect((await startButton.innerText()).match(/([\d,.]+)\s*$/)?.[1]).toBeTruthy();
        await startButton.click();
        const authDialog = page.getByRole('dialog', { name: el.processingGateAuthTitle });
        await expect(authDialog).toBeVisible();
        expect(processRequests).toBe(0);

        await authDialog.getByRole('button', {
            name: el.processingGateCreateAccount,
        }).click();
        const legalNotice = authDialog.locator('#processing-gate-register-legal-notice');
        await expect(legalNotice).toBeVisible();
        const termsLink = legalNotice.getByRole('link', {
            name: el.registerLegalTermsLink,
        });
        const privacyLink = legalNotice.getByRole('link', {
            name: el.registerLegalPrivacyLink,
        });
        await expect(termsLink).toHaveAttribute('href', '/terms');
        await expect(termsLink).toHaveAttribute('target', '_blank');
        await expect(termsLink).toHaveAttribute('rel', 'noopener noreferrer');
        await expect(privacyLink).toHaveAttribute('href', '/privacy');
        await expect(privacyLink).toHaveAttribute('target', '_blank');
        await expect(privacyLink).toHaveAttribute('rel', 'noopener noreferrer');
        await expect(authDialog.getByRole('button', {
            name: el.processingGateRegisterSubmit,
        })).toHaveAttribute(
            'aria-describedby',
            'processing-gate-register-legal-notice',
        );

        await authDialog.getByRole('button', { name: el.processingGateUseLogin }).click();
        await expect(legalNotice).toHaveCount(0);
        await expect(authDialog.getByRole('button', {
            name: el.processingGateLoginSubmit,
        })).not.toHaveAttribute('aria-describedby');

        const emailInput = page.getByLabel(el.loginEmailLabel, { exact: true });
        const passwordInput = page.getByLabel(el.loginPasswordLabel, { exact: true });
        await emailInput.fill('guest@example.com');
        await passwordInput.fill('correct horse battery staple');
        await expect(emailInput).toHaveValue('guest@example.com');
        await expect(passwordInput).toHaveValue('correct horse battery staple');
        await page.getByRole('button', { name: el.processingGateLoginSubmit }).click();

        await expect(page.getByRole('dialog', { name: el.processingGateCostTitle })).toBeVisible();
        await expect(
            page.locator('[data-testid="upload-section"] h4', { hasText: 'demo_output.mp4' }),
        ).toBeVisible();
        expect(processRequests).toBe(0);

        const processRequest = page.waitForRequest(
            request => request.method() === 'POST'
                && /\/videos\/process(?:-stream)?$/.test(request.url()),
        );
        await page.getByRole('dialog', { name: el.processingGateCostTitle }).getByRole('button', {
            name: new RegExp(el.processingGateConfirm.replace('{cost}', '\\d+')),
        }).click();
        await processRequest;
        expect(processRequests).toBe(1);
    });
});
