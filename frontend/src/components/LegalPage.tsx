'use client';

import Link from 'next/link';
import { LanguageToggle } from '@/components/LanguageToggle';
import { useI18n } from '@/context/I18nContext';
import type { MessageKey } from '@/context/i18nMessages';
import { BetaBrandLogo } from '@/components/BetaBrandLogo';
import { paidCreditLegalPublicationIsApproved } from '@/lib/paidCreditLegal';

type LegalPageKind = 'privacy' | 'terms';

interface LegalPageProps {
    kind: LegalPageKind;
}

interface LegalSection {
    id?: string;
    title: MessageKey;
    body: MessageKey;
}

const elevenLabsPrivacyLinks: ReadonlyArray<{
    href: string;
    label: MessageKey;
}> = [
    {
        href: 'https://elevenlabs.io/docs/api-reference/speech-to-text/delete',
        label: 'privacyElevenLabsDeleteLink',
    },
    {
        href: 'https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode',
        label: 'privacyElevenLabsZrmLink',
    },
    {
        href: 'https://elevenlabs.io/docs/overview/administration/data-residency',
        label: 'privacyElevenLabsResidencyLink',
    },
    {
        href: 'https://elevenlabs.io/dpa',
        label: 'privacyElevenLabsDpaLink',
    },
];

const sections: Record<LegalPageKind, LegalSection[]> = {
    privacy: [
        { title: 'privacyCollectionTitle', body: 'privacyCollectionBody' },
        { title: 'privacyRetentionTitle', body: 'privacyRetentionBody' },
        { title: 'privacyLawfulBasisTitle', body: 'privacyLawfulBasisBody' },
        { title: 'privacyPaymentsTitle', body: 'privacyPaymentsBody' },
        { title: 'privacyFinancialRetentionTitle', body: 'privacyFinancialRetentionBody' },
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

const paidCreditSections: LegalSection[] = [
    {
        id: 'seller',
        title: 'termsSellerTitle',
        body: 'termsSellerBody',
    },
    {
        id: 'paid-credits',
        title: 'termsPaidCreditsScopeTitle',
        body: 'termsPaidCreditsScopeBody',
    },
    {
        id: 'refunds',
        title: 'termsRefundsTitle',
        body: 'termsRefundsBody',
    },
    {
        title: 'termsWithdrawalTitle',
        body: 'termsWithdrawalBody',
    },
    {
        id: 'withdrawal',
        title: 'termsWithdrawalFormTitle',
        body: 'termsWithdrawalFormBody',
    },
];

export function LegalPage({ kind }: LegalPageProps) {
    const { t } = useI18n();
    const isPrivacy = kind === 'privacy';
    const titleKey: MessageKey = isPrivacy ? 'privacyPageTitle' : 'termsPageTitle';
    const introKey: MessageKey = isPrivacy ? 'privacyPageIntro' : 'termsPageIntro';
    const kickerKey: MessageKey = isPrivacy ? 'legalPrivacyKicker' : 'legalTermsKicker';
    const relatedHref = isPrivacy ? '/terms' : '/privacy';
    const relatedLabel = isPrivacy ? t('cookieTerms') : t('cookieLearnMore');
    const visibleSections = isPrivacy
        ? sections.privacy
        : paidCreditLegalPublicationIsApproved()
            ? [...sections.terms, ...paidCreditSections]
            : [
                {
                    title: 'termsPaidCreditsDraftTitle' as const,
                    body: 'termsPaidCreditsDraftBody' as const,
                },
                ...sections.terms,
            ];

    return (
        <div className="min-h-dvh bg-[#f7f7f5] text-[var(--foreground)]">
            <header className="sticky top-0 z-10 border-b border-[#e7e7e5] bg-[#f7f7f5]/95 backdrop-blur-lg">
                <div className="mx-auto flex min-h-[72px] w-full max-w-5xl items-center justify-between gap-4 px-5 sm:px-8">
                    <Link
                        href="/"
                        className="inline-flex min-h-11 items-center"
                        aria-label={t('brandHomeLabel')}
                    >
                        <BetaBrandLogo className="block h-auto w-[68px] sm:w-[72px]" />
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
                        {visibleSections.map((section) => (
                            <section
                                key={section.title}
                                id={section.id}
                                className="scroll-mt-24 border-b border-[var(--border)] py-8 sm:py-10"
                            >
                                <h2 className="text-xl font-bold tracking-[-0.02em] sm:text-2xl">{t(section.title)}</h2>
                                <p className="mt-4 text-[15px] leading-7 text-[#5f636b] sm:text-base sm:leading-8">{t(section.body)}</p>
                                {isPrivacy && section.body === 'privacyProvidersBody' && (
                                    <div className="mt-5 text-sm leading-6 text-[#5f636b]">
                                        <p className="font-semibold">{t('privacyElevenLabsLinksIntro')}</p>
                                        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-2">
                                            {elevenLabsPrivacyLinks.map((link) => (
                                                <li key={link.href}>
                                                    <a
                                                        href={link.href}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="font-semibold text-[var(--accent)] underline decoration-current underline-offset-4"
                                                    >
                                                        {t(link.label)} ↗
                                                    </a>
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
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
                    gsubs by Ascentia ↗
                </a>
            </footer>
        </div>
    );
}
