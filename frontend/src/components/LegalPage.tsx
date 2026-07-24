'use client';

import Link from 'next/link';
import { LanguageToggle } from '@/components/LanguageToggle';
import { useI18n } from '@/context/I18nContext';
import type { MessageKey } from '@/context/i18nMessages';

type LegalPageKind = 'privacy' | 'terms';

interface LegalPageProps {
    kind: LegalPageKind;
}

interface LegalSection {
    title: MessageKey;
    body: MessageKey;
}

const sections: Record<LegalPageKind, LegalSection[]> = {
    privacy: [
        { title: 'privacyCollectionTitle', body: 'privacyCollectionBody' },
        { title: 'privacyRetentionTitle', body: 'privacyRetentionBody' },
        { title: 'privacyProvidersTitle', body: 'privacyProvidersBody' },
        { title: 'privacyChoicesTitle', body: 'privacyChoicesBody' },
        { title: 'privacyCookiesTitle', body: 'privacyCookiesBody' },
        { title: 'privacyContactTitle', body: 'privacyContactBody' },
    ],
    terms: [
        { title: 'termsAcceptanceTitle', body: 'termsAcceptanceBody' },
        { title: 'termsServiceTitle', body: 'termsServiceBody' },
        { title: 'termsContentTitle', body: 'termsContentBody' },
        { title: 'termsAccuracyTitle', body: 'termsAccuracyBody' },
        { title: 'termsAvailabilityTitle', body: 'termsAvailabilityBody' },
        { title: 'termsLiabilityTitle', body: 'termsLiabilityBody' },
    ],
};

export function LegalPage({ kind }: LegalPageProps) {
    const { t } = useI18n();
    const isPrivacy = kind === 'privacy';
    const titleKey: MessageKey = isPrivacy ? 'privacyPageTitle' : 'termsPageTitle';
    const introKey: MessageKey = isPrivacy ? 'privacyPageIntro' : 'termsPageIntro';
    const kickerKey: MessageKey = isPrivacy ? 'legalPrivacyKicker' : 'legalTermsKicker';
    const relatedHref = isPrivacy ? '/terms' : '/privacy';
    const relatedLabel = isPrivacy ? t('cookieTerms') : t('cookieLearnMore');

    return (
        <div className="min-h-dvh bg-[#f7f7f5] text-[var(--foreground)]">
            <header className="sticky top-0 z-10 border-b border-[#e7e7e5] bg-[#f7f7f5]/95 backdrop-blur-lg">
                <div className="mx-auto flex min-h-[72px] w-full max-w-5xl items-center justify-between gap-4 px-5 sm:px-8">
                    <Link
                        href="/"
                        className="inline-flex min-h-11 items-center text-sm font-extrabold tracking-[0.15em]"
                        aria-label={t('brandHomeLabel')}
                    >
                        SUBFRAME
                    </Link>
                    <LanguageToggle />
                </div>
            </header>

            <main className="mx-auto w-full max-w-3xl px-5 py-10 sm:px-8 sm:py-16">
                <Link
                    href="/"
                    className="mb-10 inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-[var(--muted)] transition-colors hover:text-[var(--foreground)]"
                >
                    <span aria-hidden="true">←</span>
                    {t('legalBackHome')}
                </Link>

                <article>
                    <p className="mb-4 text-xs font-bold tracking-[0.16em] text-[var(--accent)]">{t(kickerKey)}</p>
                    <h1 className="max-w-2xl text-4xl font-extrabold tracking-[-0.045em] sm:text-6xl">{t(titleKey)}</h1>
                    <p className="mt-6 max-w-2xl text-base leading-7 text-[var(--muted)] sm:text-lg sm:leading-8">{t(introKey)}</p>
                    <p className="mt-5 text-xs font-semibold uppercase tracking-[0.12em] text-[#95989f]">{t('legalLastUpdated')}</p>

                    <div className="mt-12 border-t border-[var(--border)]">
                        {sections[kind].map((section) => (
                            <section key={section.title} className="border-b border-[var(--border)] py-8 sm:py-10">
                                <h2 className="text-xl font-bold tracking-[-0.02em] sm:text-2xl">{t(section.title)}</h2>
                                <p className="mt-4 text-[15px] leading-7 text-[#5f636b] sm:text-base sm:leading-8">{t(section.body)}</p>
                            </section>
                        ))}
                    </div>
                </article>
            </main>

            <footer className="mx-auto flex w-[calc(100%_-_2.5rem)] max-w-5xl flex-col gap-5 border-t border-[var(--border)] py-8 text-sm text-[var(--muted)] sm:w-[calc(100%_-_4rem)] sm:flex-row sm:items-center sm:justify-between">
                <Link href={relatedHref} className="inline-flex min-h-11 items-center font-semibold hover:text-[var(--foreground)]">
                    {relatedLabel}
                </Link>
                <a
                    href="https://ascentia-gp.com/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-h-11 items-center font-semibold hover:text-[var(--foreground)]"
                >
                    ASCENTIA ↗
                </a>
            </footer>
        </div>
    );
}
