'use client';

const GOOGLE_IDENTITY_SCRIPT_SRC = 'https://accounts.google.com/gsi/client';

export type GoogleCredentialResponse = {
    credential?: string;
};

type GoogleAccountsId = {
    initialize: (options: {
        client_id: string;
        callback: (response: GoogleCredentialResponse) => void;
        nonce: string;
        ux_mode: 'popup';
    }) => void;
    renderButton: (
        parent: HTMLElement,
        options: {
            type: 'standard';
            theme: 'outline';
            size: 'large';
            text: 'signin_with';
            shape: 'rectangular';
            logo_alignment: 'left';
            width: number;
            locale: string;
        },
    ) => void;
};

declare global {
    interface Window {
        google?: {
            accounts?: {
                id?: GoogleAccountsId;
            };
        };
    }
}

let googleIdentityScriptPromise: Promise<void> | null = null;

function currentScriptNonce(): string {
    const script = document.querySelector<HTMLScriptElement>('script[nonce]');
    return script?.nonce || script?.getAttribute('nonce') || '';
}

export function loadGoogleIdentityScript(): Promise<void> {
    if (typeof window === 'undefined') {
        return Promise.reject(new Error('Google login is only available in the browser.'));
    }
    if (window.google?.accounts?.id) {
        return Promise.resolve();
    }
    if (googleIdentityScriptPromise) {
        return googleIdentityScriptPromise;
    }

    googleIdentityScriptPromise = new Promise((resolve, reject) => {
        const existing = document.querySelector<HTMLScriptElement>(
            `script[src="${GOOGLE_IDENTITY_SCRIPT_SRC}"]`,
        );
        if (existing) {
            existing.addEventListener('load', () => resolve(), { once: true });
            existing.addEventListener('error', () => {
                googleIdentityScriptPromise = null;
                reject(new Error('Google login script failed to load.'));
            }, { once: true });
            return;
        }

        const script = document.createElement('script');
        script.src = GOOGLE_IDENTITY_SCRIPT_SRC;
        script.async = true;
        script.defer = true;
        const nonce = currentScriptNonce();
        if (nonce) {
            script.nonce = nonce;
        }
        script.onload = () => resolve();
        script.onerror = () => {
            googleIdentityScriptPromise = null;
            reject(new Error('Google login script failed to load.'));
        };
        document.head.appendChild(script);
    });

    return googleIdentityScriptPromise;
}

export function reloadGoogleIdentityPage(
    reload: () => void = () => window.location.reload(),
): void {
    reload();
}
