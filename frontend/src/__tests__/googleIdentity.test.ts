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
});
