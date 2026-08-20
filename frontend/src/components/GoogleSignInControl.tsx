'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';
import { api } from '@/lib/api';
import {
    loadGoogleIdentityScript,
    reloadGoogleIdentityPage,
    type GoogleCredentialResponse,
} from '@/lib/googleIdentity';
import { Spinner } from '@/components/Spinner';

type GoogleRecoveryReason = 'expired' | 'failed';

type GoogleRecoveryStrategy = 'reload-page' | 'reinitialize';

type GoogleSignInControlProps = {
    onAuthenticated: () => void | Promise<void>;
    recoveryStrategy?: GoogleRecoveryStrategy;
};

const GOOGLE_NONCE_REQUEST_SAFETY_MS = 1_000;
const GOOGLE_NONCE_REJECTION_MESSAGES = new Set([
    'Google login nonce is required.',
    'Google login nonce could not be verified.',
]);

function googleNonceUsableDurationMs(expiresInSeconds: number): number {
    const ttlMilliseconds = Math.floor(expiresInSeconds * 1_000);
    if (!Number.isFinite(ttlMilliseconds) || ttlMilliseconds <= 0) {
        return 0;
    }
    const safetyWindow = Math.min(
        GOOGLE_NONCE_REQUEST_SAFETY_MS,
        Math.floor(ttlMilliseconds / 10),
    );
    return ttlMilliseconds - safetyWindow;
}

function isGoogleNonceRejection(error: unknown): boolean {
    return error instanceof Error && GOOGLE_NONCE_REJECTION_MESSAGES.has(error.message);
}

export function GoogleSignInControl({
    onAuthenticated,
    recoveryStrategy = 'reload-page',
}: GoogleSignInControlProps) {
    const [error, setError] = useState('');
    const [googleLoading, setGoogleLoading] = useState(false);
    const [googleReady, setGoogleReady] = useState(false);
    const [googleUnavailable, setGoogleUnavailable] = useState(false);
    const [googleRecoveryReason, setGoogleRecoveryReason] =
        useState<GoogleRecoveryReason | null>(null);
    const [initializationAttempt, setInitializationAttempt] = useState(0);
    const { googleLogin } = useAuth();
    const { t } = useI18n();
    const googleButtonContainerRef = useRef<HTMLDivElement>(null);
    const googleNonceUsableUntilRef = useRef(0);
    const googleCredentialSubmittedRef = useRef(false);
    const googleInitializationGenerationRef = useRef(0);
    const googleUnavailableMessage = t('loginGoogleUnavailable');
    const googleErrorMessage = t('loginErrorGoogle');
    const googleExpiredMessage = t('loginGoogleExpired');

    const requireFreshGooglePage = useCallback((reason: GoogleRecoveryReason) => {
        googleNonceUsableUntilRef.current = 0;
        googleCredentialSubmittedRef.current = true;
        googleButtonContainerRef.current?.replaceChildren();
        setGoogleReady(false);
        setGoogleLoading(false);
        setGoogleUnavailable(false);
        setGoogleRecoveryReason(reason);
    }, []);

    const handleGoogleCredential = useCallback(async (
        credentialResponse: GoogleCredentialResponse,
        initializationGeneration: number,
    ) => {
        if (initializationGeneration !== googleInitializationGenerationRef.current) {
            return;
        }
        if (!credentialResponse.credential) {
            setError(googleErrorMessage);
            return;
        }
        if (googleCredentialSubmittedRef.current) {
            return;
        }
        if (
            googleNonceUsableUntilRef.current === 0
            || Date.now() >= googleNonceUsableUntilRef.current
        ) {
            requireFreshGooglePage('expired');
            return;
        }
        googleCredentialSubmittedRef.current = true;
        setError('');
        setGoogleLoading(true);
        try {
            await googleLogin(credentialResponse.credential);
            if (initializationGeneration !== googleInitializationGenerationRef.current) {
                return;
            }
            await onAuthenticated();
        } catch (err) {
            if (initializationGeneration !== googleInitializationGenerationRef.current) {
                return;
            }
            if (isGoogleNonceRejection(err)) {
                requireFreshGooglePage('expired');
            } else {
                setError(err instanceof Error ? err.message : googleErrorMessage);
                requireFreshGooglePage('failed');
            }
        } finally {
            if (initializationGeneration === googleInitializationGenerationRef.current) {
                setGoogleLoading(false);
            }
        }
    }, [googleErrorMessage, googleLogin, onAuthenticated, requireFreshGooglePage]);
    const handleGoogleCredentialRef = useRef(handleGoogleCredential);

    useEffect(() => {
        handleGoogleCredentialRef.current = handleGoogleCredential;
    }, [handleGoogleCredential]);

    useEffect(() => {
        const container = googleButtonContainerRef.current;
        if (!container) {
            return;
        }
        const googleButtonContainer = container;

        let cancelled = false;
        let expiryTimeoutId: number | undefined;
        const abortController = new AbortController();
        const initializationGeneration = googleInitializationGenerationRef.current + 1;
        googleInitializationGenerationRef.current = initializationGeneration;
        googleButtonContainer.replaceChildren();
        googleNonceUsableUntilRef.current = 0;
        googleCredentialSubmittedRef.current = false;
        setError('');
        setGoogleReady(false);
        setGoogleUnavailable(false);
        setGoogleRecoveryReason(null);

        async function initializeGoogle() {
            try {
                const nonce = await api.getGoogleAuthNonce(abortController.signal);
                if (
                    cancelled
                    || initializationGeneration !== googleInitializationGenerationRef.current
                ) {
                    return;
                }
                const clientId = nonce.client_id.trim();
                if (!clientId) {
                    throw new Error('Google login is unavailable.');
                }
                const nonceUsableDuration = googleNonceUsableDurationMs(nonce.expires_in);
                if (nonceUsableDuration === 0) {
                    throw new Error('Google login is unavailable.');
                }
                googleNonceUsableUntilRef.current = Date.now() + nonceUsableDuration;
                expiryTimeoutId = window.setTimeout(() => {
                    if (!cancelled && !googleCredentialSubmittedRef.current) {
                        requireFreshGooglePage('expired');
                    }
                }, nonceUsableDuration);
                await loadGoogleIdentityScript();
                if (
                    cancelled
                    || initializationGeneration !== googleInitializationGenerationRef.current
                ) {
                    return;
                }
                if (Date.now() >= googleNonceUsableUntilRef.current) {
                    requireFreshGooglePage('expired');
                    return;
                }
                const googleId = window.google?.accounts?.id;
                if (!googleId?.initialize || !googleId.renderButton) {
                    throw new Error('Google login is unavailable.');
                }
                googleId.initialize({
                    client_id: clientId,
                    nonce: nonce.nonce,
                    ux_mode: 'popup',
                    callback: (response: GoogleCredentialResponse) => {
                        if (
                            initializationGeneration
                            !== googleInitializationGenerationRef.current
                        ) {
                            return;
                        }
                        void handleGoogleCredentialRef.current(
                            response,
                            initializationGeneration,
                        );
                    },
                });
                const width = Math.max(
                    240,
                    Math.min(
                        360,
                        Math.floor(
                            googleButtonContainer.getBoundingClientRect().width || 320,
                        ),
                    ),
                );
                googleId.renderButton(googleButtonContainer, {
                    type: 'standard',
                    theme: 'outline',
                    size: 'large',
                    text: 'signin_with',
                    shape: 'rectangular',
                    logo_alignment: 'left',
                    width,
                    locale: 'el',
                });
                setGoogleReady(true);
            } catch {
                if (
                    !cancelled
                    && initializationGeneration === googleInitializationGenerationRef.current
                    && !googleCredentialSubmittedRef.current
                ) {
                    googleNonceUsableUntilRef.current = 0;
                    googleCredentialSubmittedRef.current = true;
                    setGoogleUnavailable(true);
                    setGoogleRecoveryReason(null);
                    setError('');
                }
            }
        }

        void initializeGoogle();
        return () => {
            cancelled = true;
            abortController.abort();
            if (googleInitializationGenerationRef.current === initializationGeneration) {
                googleInitializationGenerationRef.current += 1;
            }
            if (expiryTimeoutId !== undefined) {
                window.clearTimeout(expiryTimeoutId);
            }
            googleNonceUsableUntilRef.current = 0;
            googleCredentialSubmittedRef.current = true;
            googleButtonContainer.replaceChildren();
        };
    }, [initializationAttempt, requireFreshGooglePage]);

    const handleRecovery = () => {
        if (recoveryStrategy === 'reload-page') {
            reloadGoogleIdentityPage();
            return;
        }
        setGoogleRecoveryReason(null);
        setGoogleUnavailable(false);
        setInitializationAttempt((attempt) => attempt + 1);
    };

    return (
        <>
            {googleRecoveryReason ? (
                <div
                    className="auth-google-unavailable flex-col gap-2 text-center"
                    role="status"
                    aria-live="polite"
                >
                    <span>
                        {googleRecoveryReason === 'expired'
                            ? googleExpiredMessage
                            : googleErrorMessage}
                    </span>
                    <button
                        type="button"
                        onClick={handleRecovery}
                        className="font-semibold text-[var(--accent)] underline underline-offset-2"
                    >
                        {t('loginGoogleReload')}
                    </button>
                </div>
            ) : !googleUnavailable ? (
                <div
                    className="auth-google-shell"
                    aria-busy={!googleReady || googleLoading}
                >
                    <div
                        ref={googleButtonContainerRef}
                        className={googleReady
                            ? 'auth-google-official is-ready'
                            : 'auth-google-official'}
                        data-testid="google-button-container"
                    />
                    {(!googleReady || googleLoading) && (
                        <div className="auth-google-placeholder" aria-hidden={googleReady}>
                            <Spinner className="w-5 h-5 text-gray-600" />
                            <span>
                                {googleLoading
                                    ? t('loginGoogleSigningIn')
                                    : t('loginGoogleCta')}
                            </span>
                        </div>
                    )}
                </div>
            ) : (
                <div className="auth-google-unavailable" role="status">
                    {googleUnavailableMessage}
                </div>
            )}

            {error && <div className="auth-error">{error}</div>}
        </>
    );
}
