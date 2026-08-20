'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { api } from '@/lib/api';
import {
    loadGoogleIdentityScript,
    reloadGoogleIdentityPage,
    type GoogleCredentialResponse,
} from '@/lib/googleIdentity';
import { useI18n } from '@/context/I18nContext';
import { Spinner } from '@/components/Spinner';
import { BrandLogo } from '@/components/BrandLogo';

type GoogleRecoveryReason = 'expired' | 'failed';

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

export default function LoginPage() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [googleLoading, setGoogleLoading] = useState(false);
    const [googleReady, setGoogleReady] = useState(false);
    const [googleUnavailable, setGoogleUnavailable] = useState(false);
    const [googleRecoveryReason, setGoogleRecoveryReason] =
        useState<GoogleRecoveryReason | null>(null);
    const { login, googleLogin } = useAuth();
    const router = useRouter();
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
    ) => {
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
            router.push('/');
        } catch (err) {
            if (isGoogleNonceRejection(err)) {
                requireFreshGooglePage('expired');
            } else {
                setError(err instanceof Error ? err.message : googleErrorMessage);
                requireFreshGooglePage('failed');
            }
        } finally {
            setGoogleLoading(false);
        }
    }, [googleErrorMessage, googleLogin, requireFreshGooglePage, router]);
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
                        void handleGoogleCredentialRef.current(response);
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
    }, [requireFreshGooglePage]);

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        setError('');
        setIsLoading(true);

        try {
            await login(email, password);
            router.push('/');
        } catch (err) {
            setError(err instanceof Error ? err.message : t('loginErrorGeneral'));
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="auth-shell">
            <header className="auth-header">
                <Link href="/" className="auth-wordmark" aria-label={t('brandHomeLabel')}>
                    <BrandLogo className="block h-auto w-[68px] sm:w-[80px]" />
                </Link>
            </header>

            <main className="auth-main animate-fade-in">
                <section className="auth-promise" aria-labelledby="auth-promise-title">
                    <span>{t('brandBadge')}</span>
                    <h1 id="auth-promise-title">{t('heroTitle')}</h1>
                    <p>{t('heroSubtitle')}</p>
                </section>

                <section className="auth-card" aria-labelledby="login-title">
                    <div className="auth-card-heading">
                        <h2 id="login-title">{t('loginHeading')}</h2>
                        <p>{t('loginSubtitle')}</p>
                    </div>

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
                                onClick={() => reloadGoogleIdentityPage()}
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
                                className={googleReady ? 'auth-google-official is-ready' : 'auth-google-official'}
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

                    <div className="auth-divider">
                        <span>{t('loginOrEmail')}</span>
                    </div>

                    <form onSubmit={handleSubmit} className="space-y-5">
                        <div>
                            <label htmlFor="email" className="auth-label">
                                {t('loginEmailLabel')}
                            </label>
                            <input
                                id="email"
                                type="email"
                                value={email}
                                onChange={(event) => setEmail(event.target.value)}
                                className="input-field"
                                placeholder={t('loginEmailPlaceholder')}
                                autoComplete="email"
                                required
                            />
                        </div>

                        <div>
                            <label htmlFor="password" className="auth-label">
                                {t('loginPasswordLabel')}
                            </label>
                            <input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(event) => setPassword(event.target.value)}
                                className="input-field"
                                placeholder={t('loginPasswordPlaceholder')}
                                autoComplete="current-password"
                                required
                            />
                        </div>

                        {error && <div className="auth-error">{error}</div>}

                        <button
                            type="submit"
                            disabled={isLoading}
                            aria-busy={isLoading}
                            className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                        >
                            {isLoading && <Spinner className="w-5 h-5" />}
                            {isLoading ? t('loginSigningIn') : t('loginSubmit')}
                        </button>
                    </form>

                    <div className="auth-switch">
                        <p className="text-[var(--muted)]">
                            {t('loginNoAccount')}{' '}
                            <Link
                                href="/register"
                                className="text-[var(--accent)] hover:underline font-medium"
                            >
                                {t('loginCreateOne')}
                            </Link>
                        </p>
                    </div>
                </section>
            </main>

            <footer className="auth-footer">
                <span>gsubs</span>
                <span>{t('loginFooter', { year: new Date().getFullYear() })}</span>
            </footer>
        </div>
    );
}
