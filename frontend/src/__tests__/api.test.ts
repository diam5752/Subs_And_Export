// Mock fetch globally
global.fetch = jest.fn();

describe('API Client', () => {
    const originalXMLHttpRequest = global.XMLHttpRequest;

    beforeEach(() => {
        (fetch as jest.Mock).mockClear();
        localStorage.clear();
        jest.resetModules();
        global.XMLHttpRequest = originalXMLHttpRequest;
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

    describe('processVideo', () => {
        it('handles request failure with message property', async () => {
            const { api } = await import('@/lib/api');
            (global.fetch as jest.Mock).mockResolvedValue({
                ok: false,
                json: async () => ({ message: 'Custom error message' }),
            });
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            await expect(api.processVideo(file, {})).rejects.toThrow('Custom error message');
        });

        it('handles request failure with string error', async () => {
            const { api } = await import('@/lib/api');
            (global.fetch as jest.Mock).mockResolvedValue({
                ok: false,
                json: jest.fn().mockResolvedValue('Generic error string'),
            });
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            await expect(api.processVideo(file, {})).rejects.toThrow('Generic error string');
        });

        it('should upload video with settings', async () => {
            const mockResponse = { id: 'job-123', status: 'pending', progress: 0, message: null, created_at: Date.now(), updated_at: Date.now(), result_data: null };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            const result = await api.processVideo(file, { transcribe_model: 'standard', video_quality: 'high' });

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/videos/process'), expect.objectContaining({ method: 'POST' }));
            expect(result.id).toBe('job-123');
        });

        it('should use default settings when optional values are missing', async () => {
            const mockResponse = { id: 'job-def', status: 'pending', progress: 0, message: null, created_at: Date.now(), updated_at: Date.now(), result_data: null };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'default.mp4', { type: 'video/mp4' });
            await api.processVideo(file, {});

            const callArgs = (fetch as jest.Mock).mock.calls[0];
            const formData = callArgs[1].body as FormData;

            // Check defaults
            expect(formData.get('transcribe_model')).toBe('standard');
            expect(formData.get('transcribe_provider')).toBe('groq');
            expect(formData.get('video_quality')).toBe('balanced');
            expect(formData.get('subtitle_position')).toBe('16');
            expect(formData.get('max_subtitle_lines')).toBe('2');
            expect(formData.get('subtitle_size')).toBe('100');
            expect(formData.get('karaoke_enabled')).toBe('true');
        });
    });

    describe('createGcsUploadUrl', () => {
        it('should request a signed upload URL', async () => {
            const mockResponse = {
                upload_id: 'u1',
                object_name: 'uploads/u/file.mp4',
                upload_url: 'https://signed.example/upload',
                expires_at: 123,
                required_headers: { 'Content-Type': 'video/mp4' },
            };

            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => mockResponse,
            });

            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            const result = await api.createGcsUploadUrl(file);

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/videos/gcs/upload-url'),
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify({
                        filename: 'test.mp4',
                        content_type: 'video/mp4',
                        size_bytes: file.size,
                    }),
                }),
            );
            expect(result.upload_url).toBe('https://signed.example/upload');
        });
    });

    describe('uploadToSignedUrl', () => {
        it('should upload via XMLHttpRequest with progress', async () => {
            const open = jest.fn();
            const setRequestHeader = jest.fn();
            const send = jest.fn();
            const upload: Record<string, unknown> = {};
            let onload: (() => void) | null = null;

            const xhrMock = {
                open,
                setRequestHeader,
                send,
                upload,
                status: 200,
                set onload(fn: (() => void) | null) {
                    onload = fn;
                },
                get onload() {
                    return onload;
                },
                onerror: null as null | (() => void),
            };

            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (global as any).XMLHttpRequest = jest.fn(() => xhrMock);

            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            const onProgress = jest.fn();

            const promise = api.uploadToSignedUrl('https://signed.example/upload', file, 'video/mp4', onProgress);

            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (xhrMock.upload as any).onprogress({ lengthComputable: true, loaded: 50, total: 100 });
            onload?.();

            await promise;

            expect(open).toHaveBeenCalledWith('PUT', 'https://signed.example/upload');
            expect(setRequestHeader).toHaveBeenCalledWith('Content-Type', 'video/mp4');
            expect(send).toHaveBeenCalledWith(file);
            expect(onProgress).toHaveBeenCalledWith(50);
        });

        it('should reject on non-2xx status', async () => {
            const open = jest.fn();
            const setRequestHeader = jest.fn();
            const send = jest.fn();
            const upload: Record<string, unknown> = {};
            let onload: (() => void) | null = null;

            const xhrMock = {
                open,
                setRequestHeader,
                send,
                upload,
                status: 403,
                set onload(fn: (() => void) | null) {
                    onload = fn;
                },
                get onload() {
                    return onload;
                },
                onerror: null as null | (() => void),
            };

            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (global as any).XMLHttpRequest = jest.fn(() => xhrMock);

            const { api } = await import('@/lib/api');
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });

            const promise = api.uploadToSignedUrl('https://signed.example/upload', file, 'video/mp4');
            onload?.();

            await expect(promise).rejects.toThrow('Upload failed with status 403');
        });
    });

    describe('processVideoFromGcs', () => {
        it('should start processing using an upload id', async () => {
            const mockResponse = {
                id: 'job-123',
                status: 'pending',
                progress: 0,
                message: null,
                created_at: Date.now(),
                updated_at: Date.now(),
                result_data: null,
            };

            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => mockResponse,
            });

            const { api } = await import('@/lib/api');
            const result = await api.processVideoFromGcs('upload-123', { transcribe_provider: 'groq' });

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/videos/gcs/process'),
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify({
                        upload_id: 'upload-123',
                        transcribe_model: 'standard',
                        transcribe_provider: 'groq',
                        openai_model: '',
                        video_quality: 'balanced',
                        video_resolution: '',
                        use_llm: false,
                        context_prompt: '',
                        subtitle_position: 16,
                        max_subtitle_lines: 2,
                        subtitle_color: null,
                        shadow_strength: 4,
                        highlight_style: 'karaoke',
                        subtitle_size: 100,
                        karaoke_enabled: true,
                    }),
                }),
            );
            expect(result.id).toBe('job-123');
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

    describe('loadDevSampleJob', () => {
        it('should call the dev sample endpoint', async () => {
            const mockJob = { id: 'job-123', status: 'completed', progress: 100, message: 'Loaded dev sample', created_at: Date.now(), updated_at: Date.now(), result_data: { video_path: '/path', artifacts_dir: '/artifacts' } };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockJob });

            const { api } = await import('@/lib/api');
            const result = await api.loadDevSampleJob();

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/dev/sample-job'), expect.objectContaining({ method: 'POST' }));
            expect(result.id).toBe('job-123');
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

    describe('getGoogleAuthUrl', () => {
        it('should fetch Google auth URL', async () => {
            const mockResponse = { auth_url: 'https://google.com/auth', state: 'xyz789' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.getGoogleAuthUrl();

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/auth/google/url'), expect.anything());
            expect(result.auth_url).toBe('https://google.com/auth');
        });
    });

    describe('googleCallback', () => {
        it('should handle Google callback and set token', async () => {
            const mockResponse = { access_token: 'google_token', token_type: 'bearer', user_id: '456', name: 'Google User' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.googleCallback('code456', 'state456');

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/auth/google/callback'), expect.objectContaining({ method: 'POST' }));
            expect(result.access_token).toBe('google_token');
            expect(localStorage.getItem('auth_token')).toBe('google_token');
        });
    });

    describe('deleteAccount', () => {
        it('should delete account and clear token', async () => {
            localStorage.setItem('auth_token', 'existing_token');
            const mockResponse = { status: 'ok', message: 'Account deleted' };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            jest.resetModules();
            const { api } = await import('@/lib/api');
            const result = await api.deleteAccount();

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/auth/me'), expect.objectContaining({ method: 'DELETE' }));
            expect(result.status).toBe('ok');
            expect(localStorage.getItem('auth_token')).toBeNull();
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

    describe('generateViralMetadata', () => {
        it('should generate viral metadata for a job', async () => {
            const mockResponse = { hooks: ['Hook 1', 'Hook 2'], caption_hook: 'Caption', caption_body: 'Body', cta: 'Follow!', hashtags: ['#viral'] };
            (fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => mockResponse });

            const { api } = await import('@/lib/api');
            const result = await api.generateViralMetadata('job-123');

            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/videos/jobs/job-123/viral-metadata'), expect.objectContaining({ method: 'POST' }));
            expect(result.hooks).toHaveLength(2);
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
