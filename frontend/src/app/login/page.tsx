'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { api } from '@/lib/api';
import {
    loadGoogleIdentityScript,
    type GoogleCredentialResponse,
} from '@/lib/googleIdentity';
import { useI18n } from '@/context/I18nContext';
import { Spinner } from '@/components/Spinner';
import { BrandLogo } from '@/components/BrandLogo';

export default function LoginPage() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [googleLoading, setGoogleLoading] = useState(false);
    const [googleReady, setGoogleReady] = useState(false);
    const [googleUnavailable, setGoogleUnavailable] = useState(false);
    const { login, googleLogin } = useAuth();
    const router = useRouter();
    const { t } = useI18n();
    const googleButtonContainerRef = useRef<HTMLDivElement>(null);
    const googleUnavailableMessage = t('loginGoogleUnavailable');
    const googleErrorMessage = t('loginErrorGoogle');

    const handleGoogleCredential = useCallback(async (
        credentialResponse: GoogleCredentialResponse,
    ) => {
        if (!credentialResponse.credential) {
            setError(googleErrorMessage);
            return;
        }
        setError('');
        setGoogleLoading(true);
        try {
            await googleLogin(credentialResponse.credential);
            router.push('/');
        } catch (err) {
            setError(err instanceof Error ? err.message : googleErrorMessage);
        } finally {
            setGoogleLoading(false);
        }
    }, [googleErrorMessage, googleLogin, router]);
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
        googleButtonContainer.replaceChildren();
        setGoogleReady(false);
        setGoogleUnavailable(false);

        async function initializeGoogle() {
            try {
                const nonce = await api.getGoogleAuthNonce();
                const clientId = nonce.client_id.trim();
                if (!clientId) {
                    throw new Error(googleUnavailableMessage);
                }
                await loadGoogleIdentityScript();
                if (cancelled) {
                    return;
                }
                const googleId = window.google?.accounts?.id;
                if (!googleId?.initialize || !googleId.renderButton) {
                    throw new Error(googleUnavailableMessage);
                }
                googleId.initialize({
                    client_id: clientId,
                    nonce: nonce.nonce,
                    ux_mode: 'popup',
                    callback: (response: GoogleCredentialResponse) => {
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
            } catch (err) {
                if (!cancelled) {
                    const message = err instanceof Error
                        ? err.message
                        : googleUnavailableMessage;
                    setGoogleUnavailable(true);
                    setError(message === googleUnavailableMessage ? '' : message);
                }
            }
        }

        void initializeGoogle();
        return () => {
            cancelled = true;
            googleButtonContainer.replaceChildren();
        };
    }, [googleUnavailableMessage]);

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

                    {!googleUnavailable ? (
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
                        <div className="auth-google-unavailable">
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
