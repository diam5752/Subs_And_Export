/* The logo SVG is already optimized and should keep its exact intrinsic geometry. */
/* eslint-disable @next/next/no-img-element */

import { BRAND } from '@/lib/brand';

const LOGO_ASSETS = {
    horizontal: {
        light: BRAND.assets.logoLight,
        dark: BRAND.assets.logoDark,
    },
    stacked: {
        light: BRAND.assets.logoStackedLight,
        dark: BRAND.assets.logoStackedDark,
    },
} as const;

const LOGO_DIMENSIONS = {
    horizontal: { width: 640, height: 128 },
    stacked: { width: 280, height: 208 },
} as const;

interface BrandLogoProps {
    className?: string;
    surface?: 'light' | 'dark';
    markOnly?: boolean;
    layout?: 'horizontal' | 'stacked';
}

export function BrandLogo({
    className,
    surface = 'light',
    markOnly = false,
    layout = 'horizontal',
}: BrandLogoProps) {
    const src = markOnly ? BRAND.assets.mark : LOGO_ASSETS[layout][surface];
    const dimensions = markOnly
        ? { width: 256, height: 256 }
        : LOGO_DIMENSIONS[layout];

    return (
        <img
            src={src}
            alt={BRAND.name}
            className={className}
            width={dimensions.width}
            height={dimensions.height}
        />
    );
}
