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
        <div className="min-h-dvh flex items-center justify-center p-4">
            <div className="w-full max-w-md animate-fade-in">
                {/* Logo / Branding */}
                <div className="text-center mb-10">
                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[var(--accent)] mb-6">
                        <span className="text-3xl">🎬</span>
                    </div>
                    <h1 className="text-3xl font-bold text-[var(--foreground)]">{t('registerTitle')}</h1>
                    <p className="text-[var(--muted)] mt-2">{t('registerSubtitle')}</p>
                </div>

                {/* Register Card */}
                <div className="card">
                    <form onSubmit={handleSubmit} className="space-y-5">
                        <div>
                            <label htmlFor="name" className="block text-sm font-medium text-[var(--muted)] mb-2">
                                {t('registerNameLabel')}
                            </label>
                            <input
                                id="name"
                                type="text"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                className="input-field"
                                placeholder={t('registerNamePlaceholder')}
                                required
                            />
                        </div>

                        <div>
                            <label htmlFor="email" className="block text-sm font-medium text-[var(--muted)] mb-2">
                                {t('registerEmailLabel')}
                            </label>
                            <input
                                id="email"
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                className="input-field"
                                placeholder={t('registerEmailPlaceholder')}
                                required
                            />
                        </div>

                        <div>
                            <label htmlFor="password" className="block text-sm font-medium text-[var(--muted)] mb-2">
                                {t('registerPasswordLabel')}
                            </label>
                            <input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="input-field"
                                placeholder={t('registerPasswordPlaceholder')}
                                minLength={6}
                                required
                            />
                        </div>

                        {error && (
                            <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/30 text-[var(--danger)] px-4 py-3 rounded-xl text-sm">
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

                    <div className="mt-6 text-center">
                        <p className="text-[var(--muted)]">
                            {t('registerHaveAccount')}{' '}
                            <Link href="/login" className="text-[var(--accent)] hover:underline font-medium">
                                {t('registerSignIn')}
                            </Link>
                        </p>
                    </div>
                </div>

                {/* Footer */}
                <p className="text-center text-[var(--muted)] text-sm mt-8">
                    {t('loginFooter')}
                </p>
            </div>
        </div>
    );
}
