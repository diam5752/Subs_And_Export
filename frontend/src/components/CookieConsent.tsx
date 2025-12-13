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
                setVisible(true);
            }
        } catch {
            setVisible(false);
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

    if (!visible) return null;

    return (
        <div
            className="fixed bottom-[calc(env(safe-area-inset-bottom)+1rem)] left-4 z-50 w-[min(420px,calc(100vw-5rem))] animate-fade-in"
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
                            .
                        </p>
                        <div className="mt-3 flex items-center justify-end gap-2">
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
