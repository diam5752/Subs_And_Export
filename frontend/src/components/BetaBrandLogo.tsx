'use client';

import { BrandLogo } from '@/components/BrandLogo';
import { useI18n } from '@/context/I18nContext';

interface BetaBrandLogoProps {
    className?: string;
}

export function BetaBrandLogo({ className }: BetaBrandLogoProps) {
    const { t } = useI18n();

    return (
        <span className="inline-flex flex-col items-center leading-none">
            <BrandLogo className={className} />
            <span
                data-testid="beta-badge"
                className="-mt-0.5 rounded-full border border-[#cbd0d8] bg-white/85 px-1.5 py-px text-[8px] font-bold leading-3 tracking-[0.18em] text-[#737880]"
            >
                {t('betaBadge')}
            </span>
        </span>
    );
}
