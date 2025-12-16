'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useI18n } from '@/context/I18nContext';

export default function CookieConsent() {
    const { t } = useI18n();
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        try {
            const consent = localStorage.getItem('cookie-consent');
            if (!consent) {
                setTimeout(() => setVisible(true), 100);
            }
        } catch {
            // Default to hidden if local storage fails
        }
    }, []);

    const accept = () => {
        try {
            localStorage.setItem('cookie-consent', 'accepted');
        } catch {
            // Ignore write failures (e.g., private mode restrictions).
        }
        setVisible(false);
    };

    const decline = () => {
        try {
            localStorage.setItem('cookie-consent', 'declined');
        } catch {
            // Ignore write failures
        }
        setVisible(false);
    };

    if (!visible) return null;

    return (
        <div
            className="fixed inset-x-4 bottom-[calc(env(safe-area-inset-bottom)_+_1rem)] z-50 animate-fade-in sm:right-auto sm:w-[420px]"
            role="dialog"
            aria-label={t('cookieTitle')}
        >
            <div className="glass rounded-2xl px-4 py-4 shadow-2xl">
                <div className="flex items-start gap-3">
                    <div
                        className="mt-0.5 h-10 w-10 rounded-2xl bg-white/5 border border-[var(--border)] flex items-center justify-center text-lg shadow-inner"
                        aria-hidden="true"
                    >
                        🍪
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="font-semibold">{t('cookieTitle')}</div>
                        <p className="mt-1 text-sm text-[var(--muted)] leading-relaxed">
                            {t('cookieText')}{' '}
                            <Link href="/privacy" className="text-[var(--accent)] hover:underline">
                                {t('cookieLearnMore')}
                            </Link>
                            {' & '}
                            <Link href="/terms" className="text-[var(--accent)] hover:underline">
                                {t('cookieTerms')}
                            </Link>
                            .
                        </p>
                        <div className="mt-3 flex items-center justify-end gap-2">
                            <button
                                type="button"
                                onClick={decline}
                                className="px-3 py-2 text-sm text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
                            >
                                {t('cookieDecline')}
                            </button>
                            <button
                                type="button"
                                onClick={accept}
                                className="btn-secondary !px-4 !py-2 text-sm"
                            >
                                {t('cookieAccept')}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
