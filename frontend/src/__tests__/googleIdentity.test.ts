import {
    loadGoogleIdentityScript,
    reloadGoogleIdentityPage,
} from '@/lib/googleIdentity';

describe('Google Identity Services loader', () => {
    beforeEach(() => {
        document.head.replaceChildren();
        delete window.google;
    });

    it('loads the official GIS script once', async () => {
        const nextScript = document.createElement('script');
        nextScript.nonce = 'request-csp-nonce';
        document.head.appendChild(nextScript);

        const first = loadGoogleIdentityScript();
        const script = document.querySelector<HTMLScriptElement>(
            'script[src="https://accounts.google.com/gsi/client"]',
        );

        expect(script).not.toBeNull();
        expect(script?.nonce).toBe('request-csp-nonce');
        script?.dispatchEvent(new Event('load'));
        await first;

        await loadGoogleIdentityScript();
        expect(document.querySelectorAll(
            'script[src="https://accounts.google.com/gsi/client"]',
        )).toHaveLength(1);
    });

    it('uses a full-page reload to reset the nonce and GIS state', () => {
        const reload = jest.fn();

        reloadGoogleIdentityPage(reload);

        expect(reload).toHaveBeenCalledTimes(1);
    });

    it('resolves immediately when Google Identity is already available', async () => {
        const initialize = jest.fn();
        const renderButton = jest.fn();
        window.google = { accounts: { id: { initialize, renderButton } } };

        await expect(loadGoogleIdentityScript()).resolves.toBeUndefined();
        expect(document.querySelector(
            'script[src="https://accounts.google.com/gsi/client"]',
        )).toBeNull();
    });

    it('waits for an existing GIS script and clears a failed cached load', async () => {
        await jest.isolateModulesAsync(async () => {
            const { loadGoogleIdentityScript: isolatedLoad } = await import('@/lib/googleIdentity');
            const script = document.createElement('script');
            script.src = 'https://accounts.google.com/gsi/client';
            document.head.appendChild(script);

            const failed = isolatedLoad();
            script.dispatchEvent(new Event('error'));
            await expect(failed).rejects.toThrow('Google login script failed to load.');

            script.remove();
            const retried = isolatedLoad();
            const replacement = document.querySelector<HTMLScriptElement>(
                'script[src="https://accounts.google.com/gsi/client"]',
            );
            expect(replacement).not.toBeNull();
            replacement?.dispatchEvent(new Event('load'));
            await expect(retried).resolves.toBeUndefined();
        });
    });

    it('rejects a newly-created GIS script error and omits an empty nonce', async () => {
        await jest.isolateModulesAsync(async () => {
            const { loadGoogleIdentityScript: isolatedLoad } = await import('@/lib/googleIdentity');
            const pending = isolatedLoad();
            const script = document.querySelector<HTMLScriptElement>(
                'script[src="https://accounts.google.com/gsi/client"]',
            );

            expect(script?.nonce).toBe('');
            script?.dispatchEvent(new Event('error'));
            await expect(pending).rejects.toThrow('Google login script failed to load.');
        });
    });
});
