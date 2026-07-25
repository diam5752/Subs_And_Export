/* The logo SVG is already optimized and should keep its exact intrinsic geometry. */
/* eslint-disable @next/next/no-img-element */

import { BRAND } from '@/lib/brand';

interface BrandLogoProps {
    className?: string;
    surface?: 'light' | 'dark';
    markOnly?: boolean;
}

export function BrandLogo({
    className,
    surface = 'light',
    markOnly = false,
}: BrandLogoProps) {
    const src = markOnly
        ? BRAND.assets.mark
        : surface === 'dark'
            ? BRAND.assets.logoDark
            : BRAND.assets.logoLight;

    return (
        <img
            src={src}
            alt={BRAND.name}
            className={className}
            width={markOnly ? 256 : 640}
            height={markOnly ? 256 : 128}
        />
    );
}
