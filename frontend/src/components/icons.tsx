import React from 'react';

/**
 * A ultra-premium, Apple-inspired Token icon representing credits/points.
 * Features a "Royalty Gem" aesthetic with max shininess and depth.
 */
export function TokenIcon({ className = "w-4 h-4" }: { className?: string }) {
    const id = React.useId().replace(/:/g, '');
    return (
        <svg
            className={className}
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
        >
            <defs>
                {/* Deep Rich Gem Base */}
                <linearGradient id={`grad-base-${id}`} x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#4F46E5" /> {/* Deep Indigo */}
                    <stop offset="50%" stopColor="#9333EA" /> {/* Royal Purple */}
                    <stop offset="100%" stopColor="#DB2777" /> {/* Deep Pink */}
                </linearGradient>

                {/* Shimmering Light Surface */}
                <linearGradient id={`grad-shine-${id}`} x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="white" stopOpacity="0.1" />
                    <stop offset="50%" stopColor="white" stopOpacity="0.5" />
                    <stop offset="100%" stopColor="white" stopOpacity="0.1" />
                </linearGradient>

                {/* Glossy Specular Highlight */}
                <linearGradient id={`grad-gloss-${id}`} x1="50%" y1="0%" x2="50%" y2="100%">
                    <stop offset="0%" stopColor="white" stopOpacity="0.9" />
                    <stop offset="100%" stopColor="white" stopOpacity="0" />
                </linearGradient>
            </defs>

            {/* 1. The Soul (Outer Glow) */}
            <path
                d="M12 2L2 12L12 22L22 12L12 2Z"
                fill={`url(#grad-base-${id})`}
                className="opacity-40"
                filter="blur(4px)"
            />

            {/* 2. The Body (Rich Color) */}
            <path
                d="M12 2L2 12L12 22L22 12L12 2Z"
                fill={`url(#grad-base-${id})`}
                className="opacity-30"
            />

            {/* 3. The Shine (Iridescence) */}
            <path
                d="M12 2L2 12L12 22L22 12L12 2Z"
                fill={`url(#grad-shine-${id})`}
                className="opacity-40 mix-blend-overlay"
            />

            {/* 4. The Facets (Cut Edges) - Sharp & Bright */}
            <path
                d="M12 2V22M2 12H22M12 2L7 12L12 22M12 2L17 12L12 22"
                stroke="white"
                strokeWidth="0.75"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="opacity-40 mix-blend-overlay"
            />

            {/* 5. The Top Gloss (Specular Highlight) - The "Shiny" part */}
            <path
                d="M12 2L5 9L12 11L19 9L12 2Z"
                fill={`url(#grad-gloss-${id})`}
                className="opacity-40"
            />

            {/* 6. The Setting (Metal Outline) - Adapts to Text Color */}
            <path
                d="M12 2L2 12L12 22L22 12L12 2Z"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinejoin="round"
                className="opacity-80"
            />

            {/* 7. The Core Sparkle - Pure Brilliant White */}
            <path
                d="M12 8L13 11L16 12L13 13L12 16L11 13L8 12L11 11L12 8Z"
                fill="white"
                className="transform scale-75 origin-center animate-pulse-slow shadow-sm"
            />
        </svg>
    );
}

/**
 * Minimalist SF Symbols-style Refresh icon.
 */
export function RefreshIcon({ className = "w-4 h-4" }: { className?: string }) {
    return (
        <svg
            className={className}
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            <path
                d="M4.05 11a8 8 0 1 1 .5 4m-.5 5V15h5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    );
}
