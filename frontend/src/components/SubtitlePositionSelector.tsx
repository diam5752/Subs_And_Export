import React, { useCallback } from 'react';

interface SubtitlePositionSelectorProps {
    value: string;
    onChange: (value: string) => void;
    lines: number;
    onChangeLines: (lines: number) => void;
    thumbnailUrl?: string | null;
}

export function SubtitlePositionSelector({ value, onChange, lines, onChangeLines, thumbnailUrl }: SubtitlePositionSelectorProps) {
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
        { id: 'default', label: 'Default', desc: 'Social Standard' },
        { id: 'top', label: 'Middle', desc: 'Higher positioning' },
        { id: 'bottom', label: 'Low', desc: 'Cinematic style' },
    ];

    const handleLineChange = useCallback((num: number) => (e: React.MouseEvent) => {
        e.stopPropagation();
        onChangeLines(num);
    }, [onChangeLines]);

    const lineOptions = [1, 2, 3];

    return (
        <div className="space-y-4">
            <div className="flex flex-col sm:flex-row gap-5">
                {/* Controls Area */}
                <div className="flex-1 space-y-5">
                    {/* Position Selector */}
                    <div>
                        <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                            Subtitle Position
                        </label>
                        <div className="grid grid-cols-1 gap-2">
                            {options.map((opt) => (
                                <button
                                    key={opt.id}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onChange(opt.id);
                                    }}
                                    className={`p-3 rounded-lg border text-left transition-all flex items-center justify-between ${value === opt.id
                                        ? 'border-[var(--accent)]/40 bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]/40'
                                        : 'border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--surface-elevated)]'
                                        }`}
                                >
                                    <div>
                                        <div className="font-medium text-sm">{opt.label}</div>
                                        <div className="text-xs text-[var(--muted)]">{opt.desc}</div>
                                    </div>
                                    {value === opt.id && (
                                        <div className="w-2 h-2 rounded-full bg-[var(--accent)] shadow-sm" />
                                    )}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Lines Selector */}
                    <div>
                        <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                            Max Lines per Subtitle
                        </label>
                        <div className="flex bg-[var(--surface-elevated)] p-1 rounded-lg border border-[var(--border)]">
                            {lineOptions.map((num) => (
                                <button
                                    key={num}
                                    onClick={handleLineChange(num)}
                                    className={`flex-1 py-2 text-sm font-medium rounded-md transition-all ${lines === num
                                        ? 'bg-[var(--accent)]/20 text-[var(--foreground)] ring-1 ring-[var(--accent)] shadow-sm'
                                        : 'text-[var(--muted)] hover:text-[var(--foreground)]'
                                        }`}
                                >
                                    {num} Line{num > 1 ? 's' : ''}
                                </button>
                            ))}
                        </div>
                        <p className="text-xs text-[var(--muted)] mt-2">
                            Controls how much text appears at once.
                        </p>
                    </div>
                </div>

                {/* Visual Preview - Phone Mockup with optional video thumbnail */}
                <div className="flex-shrink-0 flex justify-center items-start pt-1">
                    <div className="relative w-[140px] h-[250px] bg-slate-800 rounded-[20px] border-4 border-slate-700 overflow-hidden shadow-xl ring-1 ring-white/10">
                        {/* Video Thumbnail as Background */}
                        {thumbnailUrl ? (
                            <>
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                    src={thumbnailUrl}
                                    alt="Video preview"
                                    className="absolute inset-0 w-full h-full object-cover opacity-60"
                                />
                                {/* Subtle gradient overlay for better UI visibility */}
                                <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-transparent to-black/60" />
                            </>
                        ) : (
                            /* Fallback gradient when no thumbnail */
                            <div className="absolute inset-0 bg-gradient-to-br from-slate-700 via-slate-800 to-slate-900" />
                        )}

                        {/* Phone UI Elements - Semi-transparent overlays */}
                        {/* Notch/Dynamic Island */}
                        <div className="absolute top-2 left-1/2 -translate-x-1/2 w-12 h-3 bg-black/60 rounded-full blur-[0.5px]" />

                        {/* Social Sidebar (Like/Comment/Share) */}
                        <div className="absolute bottom-16 right-2 w-6 flex flex-col gap-3 items-center">
                            <div className="w-5 h-5 bg-white/30 rounded-full shadow-sm" />
                            <div className="w-5 h-5 bg-white/30 rounded-full shadow-sm" />
                            <div className="w-5 h-5 bg-white/30 rounded-full shadow-sm" />
                        </div>

                        {/* Social Bottom Info (username, caption) */}
                        <div className="absolute bottom-4 left-3 right-10 flex flex-col gap-1.5">
                            <div className="h-2 w-3/4 bg-white/30 rounded-full" />
                            <div className="h-2 w-1/2 bg-white/25 rounded-full" />
                        </div>

                        {/* Subtitle Bar - Animated with glow */}
                        {/* We render a bar per line to visualize stacking */}
                        <div
                            className="absolute left-3 right-3 flex flex-col gap-1 items-center transition-all duration-300 ease-out subtitle-preview-bar"
                            style={{ bottom: getPreviewBottom(value) }}
                        >
                            {Array.from({ length: lines }).map((_, i) => (
                                <div
                                    key={i}
                                    className="h-3 bg-[var(--accent)]/60 rounded-sm shadow-lg w-full flex items-center justify-center opacity-90 animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-backwards"
                                    style={{
                                        width: `${85 - (i * 10)}%`, // Taper width for visual effect
                                        animationDelay: `${i * 50}ms`
                                    }}
                                >
                                    <div className="w-[90%] h-[2px] bg-white/80 rounded-full" />
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
