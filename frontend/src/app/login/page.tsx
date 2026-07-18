'use client';

import { useState, useEffect, Suspense, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { api } from '@/lib/api';
import { redirectTo } from '@/lib/navigation';
import { useI18n } from '@/context/I18nContext';
import { Spinner } from '@/components/Spinner';

function LoginContent() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [googleLoading, setGoogleLoading] = useState(false);
    const { login, googleLogin } = useAuth();
    const router = useRouter();
    const searchParams = useSearchParams();
    const { t } = useI18n();
    const hasHandledGoogleCallback = useRef(false);

    // Handle Google OAuth callback
    useEffect(() => {
        const code = searchParams.get('code');
        const state = searchParams.get('state');
        const storedState = typeof window !== 'undefined' ? localStorage.getItem('google_oauth_state') : null;

        if (hasHandledGoogleCallback.current) {
            return;
        }

        if (code && state && storedState === state) {
            hasHandledGoogleCallback.current = true;
            setGoogleLoading(true);
            // Clear immediately to avoid duplicate callback posts (e.g. React strict mode in dev).
            localStorage.removeItem('google_oauth_state');
            googleLogin(code, state)
                .then(() => {
                    router.push('/');
                })
                .catch((err) => {
                    setError(err.message || t('loginErrorGoogle'));
                })
                .finally(() => setGoogleLoading(false));
        }
    }, [searchParams, router, googleLogin, t]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
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

    const handleGoogleLogin = async () => {
        setError('');
        setGoogleLoading(true);
        try {
            const { auth_url, state } = await api.getGoogleAuthUrl();
            localStorage.setItem('google_oauth_state', state);
            redirectTo(auth_url);
        } catch (err) {
            setError(err instanceof Error ? err.message : t('loginGoogleUnavailable'));
            setGoogleLoading(false);
        }
    };

    return (
        <div className="auth-shell">
            <header className="auth-header">
                <Link href="/" className="auth-wordmark">SUBFRAME</Link>
                <span className="auth-safe-pill"><i /> Mock · €0</span>
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

                    <button
                        onClick={handleGoogleLogin}
                        disabled={googleLoading}
                        aria-busy={googleLoading}
                        className="auth-google"
                    >
                        {googleLoading ? (
                            <Spinner className="w-5 h-5 text-gray-600" />
                        ) : (
                            <svg className="w-5 h-5" viewBox="0 0 24 24">
                                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                            </svg>
                        )}
                        {googleLoading ? t('loginGoogleSigningIn') : t('loginGoogleCta')}
                    </button>

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
                                onChange={(e) => setEmail(e.target.value)}
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
                                onChange={(e) => setPassword(e.target.value)}
                                className="input-field"
                                placeholder={t('loginPasswordPlaceholder')}
                                autoComplete="current-password"
                                required
                            />
                        </div>

                        {error && (
                            <div className="auth-error">
                                {error}
                            </div>
                        )}

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
                            <Link href="/register" className="text-[var(--accent)] hover:underline font-medium">
                                {t('loginCreateOne')}
                            </Link>
                        </p>
                    </div>
                </section>
            </main>

            <footer className="auth-footer">
                <span>ASCENTIA</span>
                <span>{t('loginFooter')}</span>
            </footer>
        </div>
    );
}

export default function LoginPage() {
    return (
        <Suspense fallback={
            <div className="min-h-dvh flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-[var(--accent)]"></div>
            </div>
        }>
            <LoginContent />
        </Suspense>
    );
}
