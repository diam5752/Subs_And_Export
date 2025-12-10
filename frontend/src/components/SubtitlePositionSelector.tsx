import React from 'react';

interface SubtitlePositionSelectorProps {
    value: string;
    onChange: (value: string) => void;
    thumbnailUrl?: string | null;
}

export function SubtitlePositionSelector({ value, onChange, thumbnailUrl }: SubtitlePositionSelectorProps) {
    // Map position to CSS 'bottom' percentage for the preview
    // These are visual approximations to match the backend logic
    // Default (MarginV 320 on 1920 height) ~= 16%
    // Top (middle area) ~= 32% from bottom
    // Bottom (MarginV 120) ~= 6%
    const getPreviewBottom = (pos: string) => {
        switch (pos) {
            case 'top': return '32%';
            case 'bottom': return '6%';
            default: return '16%';
        }
    };

    const options = [
        { id: 'default', label: 'Social Default', desc: 'Optimized for Reels/TikTok UI' },
        { id: 'top', label: 'Middle / Upper', desc: 'Higher up for better visibility' },
        { id: 'bottom', label: 'Movie Style', desc: 'Cinematic low placement' },
    ];

    return (
        <div className="space-y-3">
            <label className="block text-sm font-medium text-[var(--muted)]">
                Subtitle Position
            </label>
            <div className="flex flex-col sm:flex-row gap-4">
                {/* Selection Buttons */}
                <div className="flex-1 grid grid-cols-1 gap-3">
                    {options.map((opt) => (
                        <button
                            key={opt.id}
                            onClick={(e) => {
                                e.stopPropagation();
                                onChange(opt.id);
                            }}
                            className={`p-3 rounded-lg border text-left transition-all ${value === opt.id
                                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                                : 'border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--surface-elevated)]'
                                }`}
                        >
                            <div className="font-semibold text-sm">{opt.label}</div>
                            <div className="text-xs text-[var(--muted)]">{opt.desc}</div>
                        </button>
                    ))}
                </div>

                {/* Visual Preview - Phone Mockup with optional video thumbnail */}
                <div className="flex-shrink-0 flex justify-center bg-[var(--surface-elevated)] p-4 rounded-xl border border-[var(--border)]">
                    <div className="relative w-[72px] h-[128px] bg-slate-800 rounded-xl border-2 border-slate-600 overflow-hidden shadow-lg">
                        {/* Video Thumbnail as Background */}
                        {thumbnailUrl ? (
                            <>
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                    src={thumbnailUrl}
                                    alt="Video preview"
                                    className="absolute inset-0 w-full h-full object-cover opacity-80"
                                />
                                {/* Subtle gradient overlay for better UI visibility */}
                                <div className="absolute inset-0 bg-gradient-to-b from-black/30 via-transparent to-black/40" />
                            </>
                        ) : (
                            /* Fallback gradient when no thumbnail */
                            <div className="absolute inset-0 bg-gradient-to-br from-slate-700 via-slate-800 to-slate-900" />
                        )}

                        {/* Phone UI Elements - Semi-transparent overlays */}
                        {/* Notch/Dynamic Island */}
                        <div className="absolute top-1.5 left-1/2 -translate-x-1/2 w-6 h-1.5 bg-black/60 rounded-full" />

                        {/* Social Sidebar (Like/Comment/Share) */}
                        <div className="absolute bottom-10 right-1 w-3 flex flex-col gap-1.5 items-center">
                            <div className="w-2.5 h-2.5 bg-white/40 rounded-full shadow-sm" />
                            <div className="w-2.5 h-2.5 bg-white/40 rounded-full shadow-sm" />
                            <div className="w-2.5 h-2.5 bg-white/40 rounded-full shadow-sm" />
                        </div>

                        {/* Social Bottom Info (username, caption) */}
                        <div className="absolute bottom-2 left-2 right-8 flex flex-col gap-1">
                            <div className="h-1 w-3/4 bg-white/30 rounded-full" />
                            <div className="h-1 w-1/2 bg-white/25 rounded-full" />
                        </div>

                        {/* Subtitle Bar - Animated with glow */}
                        <div
                            className="subtitle-preview-bar absolute left-1.5 right-1.5 h-4 bg-[var(--accent)] rounded-sm transition-all duration-300 ease-out flex items-center justify-center"
                            style={{ bottom: getPreviewBottom(value) }}
                        >
                            <div className="w-4/5 h-0.5 bg-white/90 rounded-full" />
                        </div>

                        {/* Decorative corner shine */}
                        <div className="absolute top-0 left-0 w-8 h-8 bg-gradient-to-br from-white/10 to-transparent pointer-events-none" />
                    </div>
                </div>
            </div>
        </div>
    );
}
