import React, { useMemo } from 'react';
import { useI18n } from '@/context/I18nContext';
import { usePoints } from '@/context/PointsContext';
import { InfoTooltip } from '@/components/InfoTooltip';
import { Spinner } from '@/components/Spinner';
import { TokenIcon, RefreshIcon } from '@/components/icons';
import {
    FACT_CHECK_COST,
    PROCESS_VIDEO_DEFAULT_COST,
    PROCESS_VIDEO_MODEL_COSTS,
    SOCIAL_COPY_COST,
    formatPoints,
} from '@/lib/points';

export function CreditsBadge() {
    const { t } = useI18n();
    const { balance, isLoading, error, refreshBalance } = usePoints();

    const formatted = useMemo(() => {
        if (typeof balance !== 'number') return '—';
        return formatPoints(balance);
    }, [balance]);

    return (
        <div className="flex items-center gap-2">
            <button
                type="button"
                onClick={() => void refreshBalance()}
                className="group inline-flex items-center gap-2.5 rounded-full border border-white/10 bg-white/5 px-3.5 py-1.5 text-sm text-[var(--foreground)] shadow-sm backdrop-blur-xl transition-all hover:bg-white/10 hover:border-[var(--accent)]/30 active:scale-[0.98] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/20"
                aria-label={t('creditsRefresh') || 'Refresh credits'}
            >
                <div className="flex items-center gap-1.5 group-hover:opacity-80 transition-opacity">
                    <TokenIcon className="w-4 h-4" />
                    <span className="font-mono text-base font-bold tracking-tight text-[var(--foreground)]">
                        {formatted}
                    </span>
                </div>

                {isLoading ? (
                    <div className="text-[var(--muted)]" aria-hidden="true">
                        <Spinner className="h-3.5 w-3.5" />
                    </div>
                ) : (
                    <div className="text-[var(--muted)] group-hover:text-[var(--foreground)]/50 transition-colors" aria-hidden="true">
                        <RefreshIcon className="w-3.5 h-3.5" />
                    </div>
                )}
            </button>

            <InfoTooltip ariaLabel={t('creditsPricingTitle') || 'Points pricing'}>
                <div className="space-y-2">
                    <div className="flex items-center justify-between gap-3">
                        <div className="font-semibold text-[11px]">{t('creditsPricingTitle') || 'Points pricing'}</div>
                        {error ? (
                            <div className="text-[10px] text-[var(--danger)]">{t('creditsError') || 'Unavailable'}</div>
                        ) : null}
                    </div>

                    <div className="space-y-1 text-[11px] text-[var(--muted)]">
                        <div className="flex items-center justify-between gap-4">
                            <span>{t('creditsCostStandard') || 'Video processing (Standard)'}</span>
                            <span className="font-mono text-[var(--foreground)]">{PROCESS_VIDEO_DEFAULT_COST}</span>
                        </div>
                        <div className="flex items-center justify-between gap-4">
                            <span>{t('creditsCostPro') || 'Video processing (Pro)'}</span>
                            <span className="font-mono text-[var(--foreground)]">{PROCESS_VIDEO_MODEL_COSTS.pro}</span>
                        </div>
                        <div className="flex items-center justify-between gap-4">
                            <span>{t('creditsCostSocialCopy') || 'Social copy'}</span>
                            <span className="font-mono text-[var(--foreground)]">{SOCIAL_COPY_COST}</span>
                        </div>
                        <div className="flex items-center justify-between gap-4">
                            <span>{t('creditsCostFactCheck') || 'Fact check'}</span>
                            <span className="font-mono text-[var(--foreground)]">{FACT_CHECK_COST}</span>
                        </div>
                    </div>

                    <div className="text-[10px] text-[var(--muted)]">
                        {t('creditsHint') || 'Charges scale with usage and apply minimums when balance is insufficient.'}
                    </div>
                </div>
            </InfoTooltip>
        </div>
    );
}
