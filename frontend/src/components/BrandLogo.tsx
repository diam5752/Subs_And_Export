/* The logo SVG is already optimized and should keep its exact intrinsic geometry. */
/* eslint-disable @next/next/no-img-element */

import { BRAND } from '@/lib/brand';

interface BrandLogoProps {
    className?: string;
    markOnly?: boolean;
}

export function BrandLogo({
    className,
    markOnly = false,
}: BrandLogoProps) {
    const src = markOnly ? BRAND.assets.mark : BRAND.assets.logo;
    const dimensions = markOnly
        ? { width: 256, height: 256 }
        : { width: 680, height: 152 };

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
