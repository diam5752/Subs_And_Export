// Mock fetch globally
global.fetch = jest.fn();

describe('API Client', () => {
    const originalXMLHttpRequest = global.XMLHttpRequest;
    const originalApiBase = process.env.NEXT_PUBLIC_API_URL;

    beforeEach(() => {
        (fetch as jest.Mock).mockClear();
        localStorage.clear();
        jest.resetModules();
        global.XMLHttpRequest = originalXMLHttpRequest;
        if (originalApiBase === undefined) {
            delete process.env.NEXT_PUBLIC_API_URL;
        } else {
            process.env.NEXT_PUBLIC_API_URL = originalApiBase;
        }
    });

    it('uses relative same-origin endpoints when the production base is explicitly empty', async () => {
        process.env.NEXT_PUBLIC_API_URL = '';
        (fetch as jest.Mock).mockResolvedValueOnce({
            ok: true,
            json: async () => ({ access_token: 'token', token_type: 'bearer', user_id: '1', name: 'QA' }),
        });

        const { API_BASE, api } = await import('@/lib/api');
        await api.login('qa@example.com', 'password123');

        expect(API_BASE).toBe('');
        expect(fetch).toHaveBeenCalledWith('/auth/token', expect.objectContaining({
            credentials: 'include',
        }));
    });

    describe('login', () => {
        it('should call the login endpoint with correct data', async () => {
            const mockResponse = {
                access_token: 'test_token',
                token_type: 'bearer',
                user_id: '123',
                name: 'Test User',
            };

            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => mockResponse,
            });

            const { api } = await import('@/lib/api');
            const result = await api.login('test@example.com', 'password123');

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/token'),
                expect.objectContaining({
                    method: 'POST',
                })
            );
            expect(result.access_token).toBe('test_token');
            expect(localStorage.getItem('auth_token')).toBe('test_token');
        });

        it('should throw error on failed login', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                json: async () => ({ detail: 'Invalid credentials' }),
            });

            const { api } = await import('@/lib/api');
            await expect(api.login('test@example.com', 'wrong')).rejects.toThrow('Invalid credentials');
        });
    });

    describe('register', () => {
        it('should call the register endpoint with correct data', async () => {
            const mockResponse = {
                id: '123',
                email: 'test@example.com',
                name: 'Test User',
                provider: 'local',
            };

            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => mockResponse,
            });

            const { api } = await import('@/lib/api');
            const result = await api.register('test@example.com', 'password123', 'Test User');

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/register'),
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify({
                        email: 'test@example.com',
                        password: 'password123',
                        name: 'Test User',
                    }),
                })
            );
            expect(result.email).toBe('test@example.com');
        });
    });

    describe('getCurrentUser', () => {
        it('should include auth header when token exists', async () => {
            localStorage.setItem('auth_token', 'stored_token');

            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ id: '123', email: 'test@example.com', name: 'Test', provider: 'local' }),
            });

            jest.resetModules();
            const { api } = await import('@/lib/api');
            await api.getCurrentUser();

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/me'),
                expect.objectContaining({
                    headers: expect.objectContaining({
                        Authorization: 'Bearer stored_token',
                    }),
                })
            );
        });
    });

    describe('revokeSession', () => {
        it('posts the current bearer token to the server logout endpoint', async () => {
            localStorage.setItem('auth_token', 'stored_token');
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ status: 'success' }),
            });

            jest.resetModules();
            const { api } = await import('@/lib/api');
            await expect(api.revokeSession()).resolves.toEqual({
                status: 'success',
            });

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/logout'),
                expect.objectContaining({
                    method: 'POST',
                    keepalive: true,
                    headers: expect.objectContaining({
                        Authorization: 'Bearer stored_token',
                    }),
                }),
            );
            expect(localStorage.getItem('auth_token')).toBe('stored_token');
        });

        it('reports a failed server revocation to its caller', async () => {
            localStorage.setItem('auth_token', 'stored_token');
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                json: async () => ({ detail: 'Could not validate credentials' }),
            });

            jest.resetModules();
            const { api } = await import('@/lib/api');

            await expect(api.revokeSession()).rejects.toThrow(
                'Could not validate credentials',
            );
        });

        it('uses the cookie-scoped endpoint when no bearer is stored', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ status: 'success' }),
            });

            const { api } = await import('@/lib/api');
            await expect(api.revokeSession()).resolves.toEqual({
                status: 'success',
            });

            expect(fetch).toHaveBeenCalledTimes(1);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/static/auth/logout'),
                expect.objectContaining({
                    method: 'POST',
                    keepalive: true,
                    credentials: 'include',
                    headers: expect.not.objectContaining({
                        Authorization: expect.any(String),
                    }),
                }),
            );
        });

        it('falls back to cookie-scoped logout after a rejected bearer', async () => {
            localStorage.setItem('auth_token', 'stale-token');
            (fetch as jest.Mock)
                .mockResolvedValueOnce({
                    ok: false,
                    status: 401,
                    json: async () => ({ detail: 'Could not validate credentials' }),
                })
                .mockResolvedValueOnce({
                    ok: true,
                    json: async () => ({ status: 'success' }),
                });

            jest.resetModules();
            const { api } = await import('@/lib/api');
            await expect(api.revokeSession()).resolves.toEqual({
                status: 'success',
            });

            expect(fetch).toHaveBeenCalledTimes(2);
            expect(fetch).toHaveBeenNthCalledWith(
                1,
                expect.stringContaining('/auth/logout'),
                expect.objectContaining({
                    headers: expect.objectContaining({
                        Authorization: 'Bearer stale-token',
                    }),
                }),
            );
            expect(fetch).toHaveBeenNthCalledWith(
                2,
                expect.stringContaining('/static/auth/logout'),
                expect.objectContaining({
                    headers: expect.not.objectContaining({
                        Authorization: expect.any(String),
                    }),
                }),
            );
        });

        it('does not mask a transient bearer logout failure with cookie fallback', async () => {
            localStorage.setItem('auth_token', 'stored-token');
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                status: 503,
                json: async () => ({ detail: 'Temporarily unavailable' }),
            });

            jest.resetModules();
            const { api } = await import('@/lib/api');

            await expect(api.revokeSession()).rejects.toThrow('Temporarily unavailable');
            expect(fetch).toHaveBeenCalledTimes(1);
        });

        it('preserves the HTTP status in a typed API error', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                status: 403,
                json: async () => ({
                    detail: 'Not authorized',
                    code: 'billing_admin_forbidden',
                }),
            });

            const { ApiError, api } = await import('@/lib/api');
            const request = api.listPendingBillingInvoices();

            await expect(request).rejects.toEqual(expect.objectContaining({
                name: 'ApiError',
                message: 'Not authorized [billing_admin_forbidden]',
                status: 403,
                code: 'billing_admin_forbidden',
            }));
            await request.catch((error: unknown) => {
                expect(error).toBeInstanceOf(ApiError);
            });
        });
    });

    describe('billing admin', () => {
        it('sends same-origin credentials when downloading a protected billing artifact', async () => {
            const artifact = new Blob(['contract'], { type: 'application/pdf' });
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                blob: async () => artifact,
            });

            const { api } = await import('@/lib/api');
            await expect(
                api.downloadBillingArtifact('/billing/purchases/purchase-1/contract'),
            ).resolves.toBe(artifact);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/billing/purchases/purchase-1/contract'),
                expect.objectContaining({
                    credentials: 'include',
                }),
            );
        });

        it('lists the first page of pending AADE records with a bounded limit', async () => {
            const response = {
                items: [],
                count: 0,
                next_cursor: null,
            };
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => response,
            });

            const { api } = await import('@/lib/api');
            await expect(api.listPendingBillingInvoices()).resolves.toEqual(response);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/billing/admin/invoices/pending?limit=50'),
                expect.objectContaining({
                    cache: 'no-store',
                }),
            );
        });

        it('encodes the server cursor when requesting the next pending page', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ items: [], count: 0, next_cursor: null }),
            });

            const { api } = await import('@/lib/api');
            await api.listPendingBillingInvoices(
                `${1_800_000_000}:${'a'.repeat(32)}`,
                25,
            );

            const requestedUrl = (fetch as jest.Mock).mock.calls[0][0] as string;
            expect(requestedUrl).toContain('/billing/admin/invoices/pending?');
            expect(requestedUrl).toContain('limit=25');
            expect(requestedUrl).toContain(
                `after=1800000000%3A${'a'.repeat(32)}`,
            );
        });

        it('records only the supplied already-issued AADE document data', async () => {
            const invoiceId = 'a'.repeat(32);
            const payload = {
                document_type: '11.2',
                series: '0',
                aa: '123',
                mark: '4000000000000123',
                issued_at: 1_800_000_000,
            };
            const response = {
                invoice_id: invoiceId,
                purchase_id: 'b'.repeat(32),
                document_status: 'issued',
                aade_document_type: payload.document_type,
                aade_series: payload.series,
                aade_aa: payload.aa,
                aade_mark: payload.mark,
                issued_at: payload.issued_at,
                recorded_at: 1_800_000_001,
                financial_retention_until: 2_000_000_000,
            };
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => response,
            });

            const { api } = await import('@/lib/api');
            await expect(
                api.recordIssuedAadeDocument(invoiceId, payload),
            ).resolves.toEqual(response);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining(
                    `/billing/admin/invoices/${invoiceId}/record-issued`,
                ),
                expect.objectContaining({
                    method: 'POST',
                    cache: 'no-store',
                    body: JSON.stringify(payload),
                }),
            );
        });

        it('encodes an invoice identifier instead of interpolating path separators', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    invoice_id: 'invalid',
                    purchase_id: 'b'.repeat(32),
                    document_status: 'issued',
                    aade_document_type: '11.2',
                    aade_series: '0',
                    aade_aa: '1',
                    aade_mark: '2',
                    issued_at: 1,
                    recorded_at: 2,
                    financial_retention_until: 2,
                }),
            });

            const { api } = await import('@/lib/api');
            await api.recordIssuedAadeDocument('unsafe/id', {
                document_type: '11.2',
                series: '0',
                aa: '1',
                mark: '2',
                issued_at: 1,
            });

            expect((fetch as jest.Mock).mock.calls[0][0]).toContain(
                '/billing/admin/invoices/unsafe%2Fid/record-issued',
            );
        });

        it('lists completed Stripe refunds awaiting AADE accounting without caching', async () => {
            const response = {
                items: [],
                count: 0,
                next_cursor: null,
            };
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => response,
            });

            const { api } = await import('@/lib/api');
            await expect(
                api.listPendingBillingRefunds(
                    `${1_800_000_000}:${'c'.repeat(32)}`,
                    25,
                ),
            ).resolves.toEqual(response);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining(
                    `/billing/admin/refunds/pending?limit=25&after=1800000000%3A${'c'.repeat(32)}`,
                ),
                expect.objectContaining({
                    cache: 'no-store',
                }),
            );
        });

        it('records only the exact completed refund and AADE evidence payload', async () => {
            const reversalId = 'unsafe/reversal';
            const payload = {
                original_document: null,
                adjustment_document: {
                    document_type: '11.4',
                    series: 'ΠΙΣ',
                    aa: '42',
                    mark: '5000000000000042',
                    issued_at: 1_800_000_100,
                },
                final_manual_actions_confirmed: true as const,
            };
            const response = {
                adjustment_id: 'd'.repeat(32),
                purchase_id: 'e'.repeat(32),
                reversal_id: 'f'.repeat(32),
                stripe_refund_id: 're_completed',
                amount_cents: 100,
                currency: 'eur',
                aade_document_type: '11.4',
                aade_series: 'ΠΙΣ',
                aade_aa: '42',
                aade_mark: '5000000000000042',
                issued_at: 1_800_000_100,
                recorded_at: 1_800_000_101,
                financial_retention_until: 2_000_000_000,
                original_invoice_status: 'issued',
                original_invoice_mark: '4000000000000042',
            };
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => response,
            });

            const { api } = await import('@/lib/api');
            await expect(
                api.recordManualRefundAccounting(reversalId, payload),
            ).resolves.toEqual(response);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining(
                    '/billing/admin/refunds/unsafe%2Freversal/record-aade-adjustment',
                ),
                expect.objectContaining({
                    method: 'POST',
                    cache: 'no-store',
                    body: JSON.stringify(payload),
                }),
            );
        });

        it('lists unresolved withdrawal requests without caching', async () => {
            const response = {
                items: [],
                count: 0,
                next_cursor: null,
            };
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => response,
            });

            const { api } = await import('@/lib/api');
            await expect(
                api.listPendingBillingWithdrawals(
                    `${1_800_000_200}:${'1'.repeat(32)}`,
                    10,
                ),
            ).resolves.toEqual(response);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining(
                    `/billing/admin/withdrawals/pending?limit=10&after=1800000200%3A${'1'.repeat(32)}`,
                ),
                expect.objectContaining({
                    cache: 'no-store',
                }),
            );
        });

        it('records one explicit human withdrawal decision without side effects', async () => {
            const withdrawalId = 'unsafe/withdrawal';
            const payload = {
                decision: 'accepted_refunded' as const,
                adjustment_id: '2'.repeat(32),
                customer_explanation: (
                    'Το εγκεκριμένο refund και το διορθωτικό ολοκληρώθηκαν.'
                ),
                final_manual_review_confirmed: true as const,
            };
            const response = {
                resolution_id: '3'.repeat(32),
                withdrawal_id: '4'.repeat(32),
                purchase_id: '5'.repeat(32),
                decision: 'accepted_refunded' as const,
                reason_code: 'accepted_after_manual_review',
                adjustment_id: payload.adjustment_id,
                resolved_at: 1_800_000_300,
                resolution_sha256: 'a'.repeat(64),
                resolution_url: '/billing/withdrawals/resolution',
            };
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => response,
            });

            const { api } = await import('@/lib/api');
            await expect(
                api.resolveBillingWithdrawal(withdrawalId, payload),
            ).resolves.toEqual(response);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining(
                    '/billing/admin/withdrawals/unsafe%2Fwithdrawal/resolve',
                ),
                expect.objectContaining({
                    method: 'POST',
                    cache: 'no-store',
                    body: JSON.stringify(payload),
                }),
            );
        });
    });

    describe('processVideo', () => {
        function installProcessXhr(status: number, payload: unknown) {
            const upload: {
                onprogress: ((event: {
                    lengthComputable: boolean;
                    loaded: number;
                    total: number;
                }) => void) | null;
                onload: (() => void) | null;
            } = {
                onprogress: null,
                onload: null,
            };
            const xhrMock = {
                open: jest.fn(),
                withCredentials: false,
                setRequestHeader: jest.fn(),
                send: jest.fn(),
                abort: jest.fn(),
                upload,
                status,
                responseText: typeof payload === 'string' ? payload : JSON.stringify(payload),
                onload: null as null | (() => void),
                onerror: null as null | (() => void),
                ontimeout: null as null | (() => void),
                onabort: null as null | (() => void),
            };
            xhrMock.abort.mockImplementation(() => xhrMock.onabort?.());
            global.XMLHttpRequest = jest.fn(() => xhrMock) as unknown as typeof XMLHttpRequest;
            return xhrMock;
        }

        it('handles request failure with message property', async () => {
            const xhrMock = installProcessXhr(400, { message: 'Custom error message' });
            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            const promise = api.processVideo(file, {});

            xhrMock.onload?.();

            await expect(promise).rejects.toThrow('Custom error message');
        });

        it('handles request failure with string error', async () => {
            const xhrMock = installProcessXhr(400, 'Generic error string');
            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            const promise = api.processVideo(file, {});

            xhrMock.onload?.();

            await expect(promise).rejects.toThrow('Generic error string');
        });

        it('uploads video with settings and reports browser upload progress', async () => {
            const mockResponse = { id: 'job-123', status: 'pending', progress: 0, message: null, created_at: Date.now(), updated_at: Date.now(), result_data: null };
            const xhrMock = installProcessXhr(200, mockResponse);
            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            const onProgress = jest.fn();
            const onUploadComplete = jest.fn();
            const promise = api.processVideo(
                file,
                { transcribe_tier: 'standard', video_quality: 'high' },
                { onProgress, onUploadComplete },
            );

            xhrMock.upload.onprogress?.({ lengthComputable: true, loaded: 51, total: 100 });
            xhrMock.upload.onload?.();
            xhrMock.onload?.();
            const result = await promise;

            expect(xhrMock.open).toHaveBeenCalledWith(
                'POST',
                expect.stringContaining('/videos/process-stream'),
            );
            expect(xhrMock.withCredentials).toBe(true);
            expect(xhrMock.send).toHaveBeenCalledWith(file);
            expect(xhrMock.setRequestHeader).toHaveBeenCalledWith('Content-Type', 'video/mp4');
            const metadataHeader = xhrMock.setRequestHeader.mock.calls.find(
                ([name]) => name === 'X-Gsubs-Upload-Metadata',
            )?.[1] as string;
            const metadata = JSON.parse(
                Buffer.from(metadataHeader, 'base64').toString('utf8'),
            ) as Record<string, unknown>;
            expect(metadata).toEqual(expect.objectContaining({
                filename: 'test.mp4',
                transcribe_tier: 'standard',
                video_quality: 'high',
            }));
            expect(onProgress).toHaveBeenCalledWith(51);
            expect(onUploadComplete).toHaveBeenCalledTimes(1);
            expect(result.id).toBe('job-123');
        });

        it('should use default settings when optional values are missing', async () => {
            const mockResponse = { id: 'job-def', status: 'pending', progress: 0, message: null, created_at: Date.now(), updated_at: Date.now(), result_data: null };
            const xhrMock = installProcessXhr(200, mockResponse);
            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'default.mp4', { type: 'video/mp4' });
            const promise = api.processVideo(file, {});

            xhrMock.onload?.();
            await promise;
            const metadataHeader = xhrMock.setRequestHeader.mock.calls.find(
                ([name]) => name === 'X-Gsubs-Upload-Metadata',
            )?.[1] as string;
            const metadata = JSON.parse(
                Buffer.from(metadataHeader, 'base64').toString('utf8'),
            ) as Record<string, unknown>;

            // Check defaults
            expect(metadata.transcribe_tier).toBe('standard');
            expect(metadata.transcribe_provider).toBe('mock');
            expect(metadata.video_quality).toBe('balanced');
            expect(metadata.subtitle_position).toBe(16);
            expect(metadata.max_subtitle_lines).toBe(2);
            expect(metadata.subtitle_size).toBe(100);
            expect(metadata.karaoke_enabled).toBe(true);
        });

        it('fails locally before creating a request when metadata cannot safely fit in the header', async () => {
            const xhrMock = installProcessXhr(200, { id: 'never-used' });
            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'oversized-settings.mp4', { type: 'video/mp4' });

            await expect(api.processVideo(file, {
                context_prompt: 'α'.repeat(5000),
            })).rejects.toMatchObject({
                name: 'ApiError',
                message: 'Upload settings are too large to send safely. Shorten the context prompt and try again.',
                status: 0,
                code: 'upload_metadata_too_large',
            });

            expect(global.XMLHttpRequest).not.toHaveBeenCalled();
            expect(xhrMock.open).not.toHaveBeenCalled();
            expect(xhrMock.send).not.toHaveBeenCalled();
        });

        it('aborts an in-flight upload without starting a second request', async () => {
            const xhrMock = installProcessXhr(200, { id: 'never-used' });
            const controller = new AbortController();
            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'cancel.mp4', { type: 'video/mp4' });
            const promise = api.processVideo(file, {}, { signal: controller.signal });

            controller.abort();

            await expect(promise).rejects.toMatchObject({ code: 'upload_cancelled' });
            expect(xhrMock.abort).toHaveBeenCalledTimes(1);
            expect(xhrMock.send).toHaveBeenCalledTimes(1);
            expect(global.XMLHttpRequest).toHaveBeenCalledTimes(1);
        });
    });

    describe('getJobStatus', () => {
        it('should fetch job status by id', async () => {
            const mockJob = { id: 'job-123', status: 'completed', progress: 100, message: 'Done', created_at: Date.now(), updated_at: Date.now(), result_data: { video_path: '/path', artifacts_dir: '/artifacts' } };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockJob });

            const { api } = await import('@/lib/api');
            const result = await api.getJobStatus('job-123');

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/videos/jobs/job-123'), expect.anything());
            expect(result.status).toBe('completed');
        });
    });

    describe('updateJobTranscription', () => {
        it('should update transcription cues for a job', async () => {
            const mockResponse = { status: 'ok' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const cues = [
                {
                    start: 0,
                    end: 1,
                    text: 'hello world',
                    words: [{ start: 0, end: 1, text: 'hello' }],
                },
            ];
            const result = await api.updateJobTranscription('job-123', cues);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/videos/jobs/job-123/transcription'),
                expect.objectContaining({ method: 'PUT', body: JSON.stringify({ cues }) })
            );
            expect(result.status).toBe('ok');
        });
    });

    describe('getJobs', () => {
        it('should fetch all jobs', async () => {
            const mockJobs = [{ id: 'job-1', status: 'completed', progress: 100, message: null, created_at: Date.now(), updated_at: Date.now(), result_data: null }];
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockJobs });

            const { api } = await import('@/lib/api');
            const result = await api.getJobs();

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/videos/jobs'), expect.anything());
            expect(result).toHaveLength(1);
        });
    });

    describe('updateProfile', () => {
        it('should update user profile', async () => {
            const mockResponse = { id: '123', email: 'test@example.com', name: 'New Name', provider: 'local' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.updateProfile('New Name');

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/auth/me'), expect.objectContaining({ method: 'PUT', body: JSON.stringify({ name: 'New Name' }) }));
            expect(result.name).toBe('New Name');
        });
    });

    describe('updatePassword', () => {
        it('should update password', async () => {
            const mockResponse = { status: 'ok' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.updatePassword('newpass', 'newpass');

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/auth/password'), expect.objectContaining({ method: 'PUT' }));
            expect(result.status).toBe('ok');
        });
    });

    describe('getHistory', () => {
        it('should fetch history events with custom limit', async () => {
            const mockHistory = [{ ts: '2024-01-01', user_id: '123', email: 'test@test.com', kind: 'video_processed', summary: 'Test', data: {} }];
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockHistory });

            const { api } = await import('@/lib/api');
            const result = await api.getHistory(10);

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/history/?limit=10'), expect.anything());
            expect(result).toHaveLength(1);
        });

        it('should fetch history events with default limit', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => [] });
            const { api } = await import('@/lib/api');
            await api.getHistory();
            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/history/?limit=50'), expect.anything());
        });
    });

    describe('getTikTokAuthUrl', () => {
        it('should fetch TikTok auth URL', async () => {
            const mockResponse = { auth_url: 'https://tiktok.com/auth', state: 'abc123' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.getTikTokAuthUrl();

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/tiktok/url'), expect.anything());
            expect(result.auth_url).toBe('https://tiktok.com/auth');
        });
    });

    describe('tiktokCallback', () => {
        it('should handle TikTok callback', async () => {
            const mockResponse = { access_token: 'tiktok_token' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.tiktokCallback('code123', 'state123');

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/tiktok/callback'), expect.objectContaining({ method: 'POST' }));
            expect(result.access_token).toBe('tiktok_token');
        });
    });

    describe('uploadToTikTok', () => {
        it('should upload to TikTok', async () => {
            const mockResponse = { success: true };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.uploadToTikTok('token', '/path/video.mp4', 'Title', 'Description');

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/tiktok/upload'), expect.objectContaining({ method: 'POST' }));
            expect(result).toEqual({ success: true });
        });
    });

    describe('getGoogleAuthNonce', () => {
        it('should fetch a Google Identity Services nonce', async () => {
            const mockResponse = {
                nonce: 'nonce-123',
                expires_in: 600,
                client_id: 'google-client-id',
            };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.getGoogleAuthNonce();

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/google/nonce'),
                expect.anything(),
            );
            expect(result.nonce).toBe('nonce-123');
        });
    });

    describe('googleLogin', () => {
        it('should exchange a verified Google ID token for a session', async () => {
            const mockResponse = { access_token: 'google_token', token_type: 'bearer', user_id: '456', name: 'Google User' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.googleLogin('signed-google-id-token');

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/google'),
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify({ id_token: 'signed-google-id-token' }),
                }),
            );
            expect(result.access_token).toBe('google_token');
            expect(localStorage.getItem('auth_token')).toBe('google_token');
        });
    });

    describe('deleteAccount', () => {
        it('should delete account and clear token', async () => {
            localStorage.setItem('auth_token', 'existing_token');
            localStorage.setItem('lastActiveJobId', 'private-job');
            const mockResponse = { status: 'ok', message: 'Account deleted' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            jest.resetModules();
            const { api } = await import('@/lib/api');
            const result = await api.deleteAccount();

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/auth/me'), expect.objectContaining({ method: 'DELETE' }));
            expect(result.status).toBe('ok');
            expect(localStorage.getItem('auth_token')).toBeNull();
            expect(localStorage.getItem('lastActiveJobId')).toBeNull();
        });
    });

    describe('deleteJob', () => {
        it('should delete a job', async () => {
            const mockResponse = { status: 'ok', job_id: 'job-123' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.deleteJob('job-123');

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/videos/jobs/job-123'), expect.objectContaining({ method: 'DELETE' }));
            expect(result.job_id).toBe('job-123');
        });
    });

    describe('deleteJobs', () => {
        it('should batch delete jobs using the backend route contract', async () => {
            const mockResponse = { status: 'deleted', deleted_count: 2 };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.deleteJobs(['job-1', 'job-2']);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/videos/jobs/batch-delete'),
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify({ job_ids: ['job-1', 'job-2'] }),
                }),
            );
            expect(result.deleted_count).toBe(2);
        });
    });



    describe('error handling', () => {
        it('should handle string error responses', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: false, json: async () => 'String error message' });

            const { api } = await import('@/lib/api');
            await expect(api.getCurrentUser()).rejects.toThrow('String error message');
        });

        it('should handle error.message format', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: false, json: async () => ({ message: 'Message error' }) });

            const { api } = await import('@/lib/api');
            await expect(api.getCurrentUser()).rejects.toThrow('Message error');
        });

        it('should handle JSON parse failure gracefully', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: false, json: async () => { throw new Error('Parse error'); } });

            const { api } = await import('@/lib/api');
            await expect(api.getCurrentUser()).rejects.toThrow('Request failed');
        });

        it('should handle error object with detail as object', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                json: async () => ({ detail: { info: 'Complex error' } })
            });

            const { api } = await import('@/lib/api');
            await expect(api.getCurrentUser()).rejects.toThrow('{"info":"Complex error"}');
        });

        it('should handle error with message property', async () => {
            (fetch as jest.Mock).mockResolvedValue({
                ok: false,
                json: async () => ({ message: 'Error message prop' }),
            });
            const { api } = await import('@/lib/api');
            // Assuming we can use processVideo or simply check request generally
            // But we need to call something that uses request(). getCurrentUser does.
            await expect(api.getCurrentUser()).rejects.toThrow('Error message prop');
        });
    });
});

describe('Token Management', () => {
    beforeEach(() => {
        localStorage.clear();
        jest.resetModules();
    });

    it('should store token in localStorage', async () => {
        const { api } = await import('@/lib/api');
        api.setToken('new_token');
        expect(localStorage.getItem('auth_token')).toBe('new_token');
    });

    it('should clear token from localStorage', async () => {
        localStorage.setItem('auth_token', 'existing_token');
        const { api } = await import('@/lib/api');
        api.clearToken();
        expect(localStorage.getItem('auth_token')).toBeNull();
    });
});
