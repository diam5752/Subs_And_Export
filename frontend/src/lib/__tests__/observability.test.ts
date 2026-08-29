import {
    exportFormatBucket,
    fetchObservabilitySnapshot,
    reportApiFailure,
    reportPresence,
    reportProductAction,
} from '@/lib/observability';

const fetchMock = jest.fn();

describe('privacy-bounded observability client', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        process.env.NEXT_PUBLIC_ENABLE_TEST_OBSERVABILITY = '1';
        localStorage.clear();
        Object.defineProperty(globalThis, 'fetch', {
            configurable: true,
            value: fetchMock,
        });
        fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
        window.history.replaceState({}, '', '/');
    });

    afterEach(() => {
        delete process.env.NEXT_PUBLIC_ENABLE_TEST_OBSERVABILITY;
    });

    it('sends only fixed presence and action fields with the bearer token', () => {
        localStorage.setItem('auth_token', 'test-session');

        reportPresence();
        reportProductAction('export_started', {
            outcome: 'started',
            exportFormat: '1080p',
        });

        expect(fetchMock).toHaveBeenCalledTimes(2);
        const presenceRequest = fetchMock.mock.calls[0][1] as RequestInit;
        const actionRequest = fetchMock.mock.calls[1][1] as RequestInit;
        const presence = JSON.parse(String(presenceRequest.body));
        const action = JSON.parse(String(actionRequest.body));
        expect(presence).toEqual(expect.objectContaining({
            kind: 'presence',
            route: 'studio',
        }));
        expect(presence.presence_id).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
        expect(action).toEqual(expect.objectContaining({
            kind: 'action',
            name: 'export_started',
            export_format: '1080p',
        }));
        expect(JSON.stringify([presence, action])).not.toMatch(/message|filename|email|user_id|stack/i);
        expect(actionRequest.headers).toEqual(expect.objectContaining({
            Authorization: 'Bearer test-session',
        }));
    });

    it('reduces API failures to endpoint and status buckets', () => {
        reportApiFailure('/videos/jobs/private-job-id/export', {
            status: 503,
            code: 'provider_message_that_must_not_leave',
        });

        const payload = JSON.parse(String(fetchMock.mock.calls[0][1].body));
        expect(payload).toEqual(expect.objectContaining({
            kind: 'api_error',
            name: 'http_5xx',
            status_code: 503,
            route: 'studio',
        }));
        expect(JSON.stringify(payload)).not.toContain('private-job-id');
        expect(JSON.stringify(payload)).not.toContain('provider_message');
    });

    it('does not report normal user upload cancellation', () => {
        reportApiFailure('/videos/process-stream', {
            status: 0,
            code: 'upload_cancelled',
        });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('does not emit observability requests during ordinary Jest runs', () => {
        delete process.env.NEXT_PUBLIC_ENABLE_TEST_OBSERVABILITY;

        reportPresence();
        reportProductAction('app_opened');

        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('buckets public page routes and viewport sizes without storing paths', () => {
        const cases = [
            ['/login', 500, 'auth', 'compact'],
            ['/account/history', 800, 'account', 'regular'],
            ['/billing/credits', 1_400, 'billing', 'wide'],
            ['/admin/observability', 800, 'observability', 'regular'],
            ['/privacy', 800, 'legal', 'regular'],
            ['/feedback/private-value', 800, 'other', 'regular'],
        ] as const;

        for (const [path, width, route, viewport] of cases) {
            window.history.replaceState({}, '', path);
            Object.defineProperty(window, 'innerWidth', {
                configurable: true,
                value: width,
            });
            reportProductAction('app_opened');
            const payload = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body));
            expect(payload).toEqual(expect.objectContaining({ route, viewport }));
            expect(JSON.stringify(payload)).not.toContain(path);
        }
    });

    it('maps API endpoints and failures to bounded categories', () => {
        const cases = [
            ['/auth/token', { code: 'request_timeout', status: 408 }, 'auth', 'request_timeout'],
            ['/billing/private', { status: 404 }, 'billing', 'http_4xx'],
            ['/feedback/private', 'raw private error', 'feedback', 'unknown_error'],
            ['/history/private', {}, 'account', 'network_error'],
            ['/videos/private', { code: 'provider-private' }, 'studio', 'network_error'],
            ['/other/private', { status: 302 }, 'other', 'network_error'],
        ] as const;

        for (const [endpoint, error, route, name] of cases) {
            reportApiFailure(endpoint, error);
            const payload = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body));
            expect(payload).toEqual(expect.objectContaining({ route, name }));
            expect(JSON.stringify(payload)).not.toMatch(/private|provider-private|raw private error/);
        }
    });

    it('keeps best-effort delivery failures inside the diagnostics client', async () => {
        fetchMock.mockRejectedValueOnce(new Error('private network detail'));

        reportPresence();
        await Promise.resolve();
        await Promise.resolve();

        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it('fetches the owner snapshot without caching', async () => {
        const snapshot = { generated_at: 1 };
        fetchMock.mockResolvedValue({ ok: true, json: async () => snapshot });

        await expect(fetchObservabilitySnapshot()).resolves.toEqual(snapshot);
        expect(fetchMock).toHaveBeenCalledWith(
            expect.stringContaining('/observability/admin/snapshot'),
            expect.objectContaining({ cache: 'no-store' }),
        );
    });

    it('fails a denied owner snapshot without exposing its body', async () => {
        fetchMock.mockResolvedValue({ ok: false, status: 403 });

        await expect(fetchObservabilitySnapshot()).rejects.toThrow(
            'observability_snapshot_403',
        );
    });

    it('normalizes every public export option', () => {
        expect(['720x1280', '1080x1920', '2160x3840', 'srt', 'vtt', 'txt', 'weird'].map(
            exportFormatBucket,
        )).toEqual(['720p', '1080p', '4k', 'srt', 'vtt', 'txt', 'other']);
    });
});
