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
            className="cookie-consent fixed inset-x-3 bottom-[calc(env(safe-area-inset-bottom)_+_0.75rem)] z-50 animate-fade-in sm:left-5 sm:right-auto sm:w-[390px]"
            role="dialog"
            aria-label={t('cookieTitle')}
            aria-describedby="cookie-consent-description"
        >
            <div className="cookie-consent-card glass rounded-2xl px-3 py-3 shadow-2xl sm:px-4 sm:py-4">
                <div className="flex items-start gap-2.5 sm:gap-3">
                    <div
                        className="mt-0.5 hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-white/5 text-base shadow-inner sm:flex"
                        aria-hidden="true"
                    >
                        🍪
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold sm:text-base">{t('cookieTitle')}</div>
                        <p
                            id="cookie-consent-description"
                            className="mt-0.5 text-xs leading-[1.45] text-[var(--muted)] sm:mt-1 sm:text-sm sm:leading-relaxed"
                        >
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
                        <div className="mt-2 flex items-center justify-end gap-1.5 sm:mt-3 sm:gap-2">
                            <button
                                type="button"
                                onClick={decline}
                                className="min-h-11 rounded-lg px-3 py-2 text-xs text-[var(--muted)] transition-colors hover:bg-black/[0.03] hover:text-[var(--foreground)] sm:text-sm"
                            >
                                {t('cookieDecline')}
                            </button>
                            <button
                                type="button"
                                onClick={accept}
                                className="btn-secondary min-h-11 !px-4 !py-2 text-xs sm:text-sm"
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
