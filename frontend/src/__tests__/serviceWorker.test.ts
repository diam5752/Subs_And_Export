import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';

type WorkerEvent = {
    request: {
        method: string;
        url: string;
        mode: string;
        headers: {
            get: (name: string) => string | null;
        };
    };
    respondWith: jest.Mock<void, [Promise<unknown>]>;
};

type LifecycleEvent = {
    waitUntil: jest.Mock<void, [Promise<unknown>]>;
};

type EventListeners = {
    activate?: (event: LifecycleEvent) => void;
    fetch?: (event: WorkerEvent) => void;
    install?: (event: LifecycleEvent) => void;
};

function createHarness(options?: {
    cacheKeys?: string[];
    cachedResponse?: unknown;
}) {
    const listeners: EventListeners = {};
    const cache = {
        addAll: jest.fn().mockResolvedValue(undefined),
        put: jest.fn().mockResolvedValue(undefined),
    };
    const caches = {
        delete: jest.fn().mockResolvedValue(true),
        keys: jest.fn().mockResolvedValue(options?.cacheKeys ?? []),
        match: jest.fn().mockResolvedValue(options?.cachedResponse ?? null),
        open: jest.fn().mockResolvedValue(cache),
    };
    const fetch = jest.fn();
    const clients = {
        claim: jest.fn(),
    };
    const workerSelf = {
        addEventListener: jest.fn((
            type: keyof EventListeners,
            listener: NonNullable<EventListeners[typeof type]>,
        ) => {
            listeners[type] = listener as never;
        }),
        clients,
        location: {
            origin: 'https://gsubs.example',
        },
        skipWaiting: jest.fn(),
    };
    const source = readFileSync(
        resolve(process.cwd(), 'public/sw.js'),
        'utf8',
    );

    runInNewContext(source, {
        Promise,
        URL,
        caches,
        fetch,
        self: workerSelf,
    });

    return {
        cache,
        caches,
        clients,
        fetch,
        listeners,
    };
}

function fetchEvent({
    authorization = null,
    mode = 'cors',
    path,
}: {
    authorization?: string | null;
    mode?: string;
    path: string;
}): WorkerEvent {
    return {
        request: {
            method: 'GET',
            mode,
            url: `https://gsubs.example${path}`,
            headers: {
                get: (name: string) => (
                    name.toLowerCase() === 'authorization'
                        ? authorization
                        : null
                ),
            },
        },
        respondWith: jest.fn(),
    };
}

describe('service worker cache boundaries', () => {
    it.each([
        {
            name: 'billing admin JSON',
            event: fetchEvent({
                path: '/billing/admin/invoices/pending?limit=50',
            }),
        },
        {
            name: 'admin navigation',
            event: fetchEvent({
                mode: 'navigate',
                path: '/admin/billing',
            }),
        },
        {
            name: 'authenticated same-origin request',
            event: fetchEvent({
                authorization: 'Bearer private-token',
                path: '/manifest.webmanifest',
            }),
        },
    ])('bypasses $name without consulting or writing Cache Storage', ({ event }) => {
        const harness = createHarness();

        harness.listeners.fetch?.(event);

        expect(event.respondWith).not.toHaveBeenCalled();
        expect(harness.caches.match).not.toHaveBeenCalled();
        expect(harness.caches.open).not.toHaveBeenCalled();
        expect(harness.cache.put).not.toHaveBeenCalled();
        expect(harness.fetch).not.toHaveBeenCalled();
    });

    it('purges previous shell caches during v4 activation', async () => {
        // REGRESSION: Installed clients kept the old icon after the canonical
        // compact-split brand assets replaced the direct-morph artwork.
        const harness = createHarness({
            cacheKeys: ['gsubs-shell-v2', 'gsubs-shell-v3', 'gsubs-shell-v4'],
        });
        const event: LifecycleEvent = {
            waitUntil: jest.fn(),
        };

        harness.listeners.activate?.(event);

        expect(event.waitUntil).toHaveBeenCalledTimes(1);
        await event.waitUntil.mock.calls[0][0];
        expect(harness.caches.delete).toHaveBeenCalledTimes(2);
        expect(harness.caches.delete).toHaveBeenCalledWith('gsubs-shell-v2');
        expect(harness.caches.delete).toHaveBeenCalledWith('gsubs-shell-v3');
        expect(harness.caches.delete).not.toHaveBeenCalledWith('gsubs-shell-v4');
        expect(harness.clients.claim).toHaveBeenCalledTimes(1);
    });

    it('continues caching a safe unauthenticated same-origin static asset', async () => {
        const harness = createHarness();
        const response = {
            ok: true,
            clone: jest.fn(() => ({ copy: true })),
        };
        harness.fetch.mockResolvedValue(response);
        const event = fetchEvent({ path: '/icon.png' });

        harness.listeners.fetch?.(event);

        expect(event.respondWith).toHaveBeenCalledTimes(1);
        await expect(event.respondWith.mock.calls[0][0]).resolves.toBe(response);
        await Promise.resolve();
        expect(harness.caches.match).toHaveBeenCalledWith(event.request);
        expect(harness.fetch).toHaveBeenCalledWith(event.request);
        expect(harness.caches.open).toHaveBeenCalledWith('gsubs-shell-v4');
        expect(response.clone).toHaveBeenCalledTimes(1);
        expect(harness.cache.put).toHaveBeenCalledWith(
            event.request,
            { copy: true },
        );
    });
});
