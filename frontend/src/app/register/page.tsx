'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';
import { Spinner } from '@/components/Spinner';

export default function RegisterPage() {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const { register } = useAuth();
    const router = useRouter();
    const { t } = useI18n();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);

        try {
            await register(email, password, name);
            router.push('/');
        } catch (err) {
            setError(err instanceof Error ? err.message : t('registerError'));
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="auth-shell">
            <header className="auth-header">
                <Link href="/" className="auth-wordmark">SUBFRAME</Link>
                <span className="auth-safe-pill"><i /> Mock · €0</span>
            </header>

            <main className="auth-main animate-fade-in">
                <section className="auth-promise" aria-labelledby="register-promise-title">
                    <span>{t('brandBadge')}</span>
                    <h1 id="register-promise-title">{t('heroTitle')}</h1>
                    <p>{t('heroSubtitle')}</p>
                </section>

                <section className="auth-card" aria-labelledby="register-title">
                    <div className="auth-card-heading">
                        <h2 id="register-title">{t('registerTitle')}</h2>
                        <p>{t('registerSubtitle')}</p>
                    </div>
                    <form onSubmit={handleSubmit} className="space-y-5">
                        <div>
                            <label htmlFor="name" className="auth-label">
                                {t('registerNameLabel')}
                            </label>
                            <input
                                id="name"
                                type="text"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                className="input-field"
                                placeholder={t('registerNamePlaceholder')}
                                autoComplete="name"
                                required
                            />
                        </div>

                        <div>
                            <label htmlFor="email" className="auth-label">
                                {t('registerEmailLabel')}
                            </label>
                            <input
                                id="email"
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                className="input-field"
                                placeholder={t('registerEmailPlaceholder')}
                                autoComplete="email"
                                required
                            />
                        </div>

                        <div>
                            <label htmlFor="password" className="auth-label">
                                {t('registerPasswordLabel')}
                            </label>
                            <input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="input-field"
                                placeholder={t('registerPasswordPlaceholder')}
                                minLength={12}
                                autoComplete="new-password"
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
                            {isLoading ? t('registerSubmitting') : t('registerSubmit')}
                        </button>
                    </form>

                    <div className="auth-switch">
                        <p className="text-[var(--muted)]">
                            {t('registerHaveAccount')}{' '}
                            <Link href="/login" className="text-[var(--accent)] hover:underline font-medium">
                                {t('registerSignIn')}
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
