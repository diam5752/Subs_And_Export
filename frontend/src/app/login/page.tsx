'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { api } from '@/lib/api';

export default function LoginPage() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [googleLoading, setGoogleLoading] = useState(false);
    const { login } = useAuth();
    const router = useRouter();
    const searchParams = useSearchParams();

    // Handle Google OAuth callback
    useEffect(() => {
        const code = searchParams.get('code');
        const state = searchParams.get('state');
        const storedState = typeof window !== 'undefined' ? localStorage.getItem('google_oauth_state') : null;

        if (code && state && storedState === state) {
            setGoogleLoading(true);
            api.googleCallback(code, state)
                .then(() => {
                    localStorage.removeItem('google_oauth_state');
                    router.push('/');
                })
                .catch((err) => {
                    setError(err.message || 'Google login failed');
                    localStorage.removeItem('google_oauth_state');
                })
                .finally(() => setGoogleLoading(false));
        }
    }, [searchParams, router]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);

        try {
            await login(email, password);
            router.push('/');
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Login failed');
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
            window.location.href = auth_url;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Google login not available');
            setGoogleLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center p-4">
            <div className="w-full max-w-md animate-fade-in">
                {/* Logo / Branding */}
                <div className="text-center mb-10">
                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[var(--accent)] mb-6">
                        <span className="text-3xl">🎬</span>
                    </div>
                    <h1 className="text-3xl font-bold text-[var(--foreground)]">Greek Sub Publisher</h1>
                    <p className="text-[var(--muted)] mt-2">Transform your videos with AI-powered Greek subtitles</p>
                </div>

                {/* Login Card */}
                <div className="card">
                    <h2 className="text-xl font-semibold mb-6 text-center">Sign in to your account</h2>

                    {/* Google Login Button */}
                    <button
                        onClick={handleGoogleLogin}
                        disabled={googleLoading}
                        className="w-full flex items-center justify-center gap-3 bg-white text-gray-800 font-medium py-3 px-4 rounded-xl hover:bg-gray-100 transition-colors disabled:opacity-50 mb-6"
                    >
                        <svg className="w-5 h-5" viewBox="0 0 24 24">
                            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                        </svg>
                        {googleLoading ? 'Signing in...' : 'Continue with Google'}
                    </button>

                    <div className="relative mb-6">
                        <div className="absolute inset-0 flex items-center">
                            <div className="w-full border-t border-[var(--border)]"></div>
                        </div>
                        <div className="relative flex justify-center text-sm">
                            <span className="px-4 bg-[var(--surface)] text-[var(--muted)]">or continue with email</span>
                        </div>
                    </div>

                    <form onSubmit={handleSubmit} className="space-y-5">
                        <div>
                            <label htmlFor="email" className="block text-sm font-medium text-[var(--muted)] mb-2">
                                Email Address
                            </label>
                            <input
                                id="email"
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                className="input-field"
                                placeholder="you@example.com"
                                required
                            />
                        </div>

                        <div>
                            <label htmlFor="password" className="block text-sm font-medium text-[var(--muted)] mb-2">
                                Password
                            </label>
                            <input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="input-field"
                                placeholder="••••••••"
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
                            className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isLoading ? 'Signing in...' : 'Sign In'}
                        </button>
                    </form>

                    <div className="mt-6 text-center">
                        <p className="text-[var(--muted)]">
                            Don&apos;t have an account?{' '}
                            <Link href="/register" className="text-[var(--accent)] hover:underline font-medium">
                                Create one
                            </Link>
                        </p>
                    </div>
                </div>

                {/* Footer */}
                <p className="text-center text-[var(--muted)] text-sm mt-8">
                    © 2024 Greek Sub Publisher. All rights reserved.
                </p>
            </div>
        </div>
    );
}
