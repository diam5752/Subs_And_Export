'use client';

import { BrandLogo } from '@/components/BrandLogo';
import { LanguageToggle } from '@/components/LanguageToggle';
import { useI18n } from '@/context/I18nContext';

interface SessionRecoveryScreenProps {
    onRetry: () => Promise<void>;
}

export function SessionRecoveryScreen({ onRetry }: SessionRecoveryScreenProps) {
    const { t } = useI18n();

    return (
        <main className="relative grid min-h-dvh place-items-center overflow-hidden bg-[#f7f7f5] px-5 py-20 text-[#171716]">
            <div className="absolute right-4 top-[max(1rem,env(safe-area-inset-top))]">
                <LanguageToggle />
            </div>
            <section className="w-full max-w-md rounded-[28px] border border-[#dededb] bg-white p-7 text-center shadow-[0_18px_60px_rgba(26,30,36,0.08)] sm:p-10">
                <BrandLogo className="mx-auto block h-auto w-24" />
                <h1 className="mt-7 text-balance text-2xl font-bold tracking-[-0.035em] sm:text-3xl">
                    {t('sessionUnavailableTitle')}
                </h1>
                <p className="mx-auto mt-4 max-w-sm text-pretty text-sm leading-6 text-[#5f625f] sm:text-base">
                    {t('sessionUnavailableBody')}
                </p>
                <button
                    type="button"
                    onClick={() => void onRetry()}
                    className="mt-7 inline-flex min-h-12 w-full items-center justify-center rounded-full bg-[#171716] px-5 text-sm font-semibold text-white transition-colors hover:bg-[#30302e] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#171716]"
                >
                    {t('sessionRetry')}
                </button>
            </section>
        </main>
    );
}
