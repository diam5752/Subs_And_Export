'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';
import { Spinner } from '@/components/Spinner';
import { BetaBrandLogo } from '@/components/BetaBrandLogo';
import { GoogleSignInControl } from '@/components/GoogleSignInControl';

export default function LoginPage() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const { login } = useAuth();
    const router = useRouter();
    const { t } = useI18n();

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
                    <BetaBrandLogo className="block h-auto w-[68px] sm:w-[72px]" />
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

                    <GoogleSignInControl onAuthenticated={() => router.push('/')} />

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
