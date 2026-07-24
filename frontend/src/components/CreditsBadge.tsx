import React, { useMemo } from 'react';
import { useI18n } from '@/context/I18nContext';
import { usePoints } from '@/context/PointsContext';
import { Spinner } from '@/components/Spinner';
import { CoinsIcon } from '@/components/icons';
import { formatPoints } from '@/lib/points';

export function CreditsBadge({ onClick }: { onClick?: () => void }) {
    const { t } = useI18n();
    const { balance, isLoading, error, refreshBalance } = usePoints();

    const formatted = useMemo(() => {
        if (typeof balance !== 'number') return '—';
        return formatPoints(balance);
    }, [balance]);
    const label = `${t('creditsLabel') || 'Credits'}: ${formatted}`;

    return (
        <button
            type="button"
            onClick={() => {
                if (onClick) {
                    onClick();
                    return;
                }
                void refreshBalance();
            }}
            className="studio-credit-balance"
            aria-label={label}
            aria-busy={isLoading}
            title={error ? (t('creditsError') || 'Unavailable') : label}
            data-testid="credits-balance"
        >
            <span className="studio-credit-icon" data-testid="credits-coin-icon">
                <CoinsIcon className="h-4 w-4" />
            </span>
            <span className="studio-credit-value" aria-live="polite">{formatted}</span>
            {onClick ? <span aria-hidden="true" className="text-[11px] font-bold opacity-70">+</span> : null}
            {isLoading ? <Spinner className="h-3 w-3" /> : null}
        </button>
    );
}
