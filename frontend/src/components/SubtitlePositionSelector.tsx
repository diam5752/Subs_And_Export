import React, { useCallback } from 'react';

interface SubtitlePositionSelectorProps {
    value: string;
    onChange: (value: string) => void;
    lines: number;
    onChangeLines: (lines: number) => void;
    thumbnailUrl?: string | null;
    previewColor?: string;
    disableMaxLines?: boolean;
}

export function SubtitlePositionSelector({ value, onChange, lines, onChangeLines, thumbnailUrl, previewColor, subtitleColor, onChangeColor, colors, disableMaxLines }: SubtitlePositionSelectorProps & { subtitleColor?: string, onChangeColor?: (color: string) => void, colors?: Array<{ label: string; value: string; ass: string }> }) {
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
        { id: 'top', label: 'Middle', desc: 'Higher positioning' },
        { id: 'default', label: 'Default', desc: 'Social Standard' },
        { id: 'bottom', label: 'Low', desc: 'Cinematic style' },
    ];

    const handleLineChange = useCallback((num: number) => (e: React.MouseEvent) => {
        e.stopPropagation();
        onChangeLines(num);
    }, [onChangeLines]);

    const lineOptions = [
        { value: 0, label: '1 Word at a Time', desc: 'Karaoke style' },
        { value: 1, label: 'Single Line', desc: 'Minimalist look' },
        { value: 2, label: 'Double Line', desc: 'Standard balance' },
        { value: 3, label: 'Three Lines', desc: 'Maximum context' },
    ];

    return (
        <div className="space-y-4">
            <div className="flex flex-col xl:flex-row gap-5">
                {/* Controls Area */}
                <div className="flex-1 flex flex-col md:flex-row gap-6">
                    {/* Position Selector */}
                    <div className="flex-1 min-w-[200px]">
                        <label className="block text-sm font-medium text-[var(--muted)] mb-3">
                            Subtitle Position
                        </label>
                        <div className="flex flex-col gap-2">
                            {options.map((opt) => (
                                <button
                                    key={opt.id}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onChange(opt.id);
                                    }}
                                    className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between group ${value === opt.id
                                        ? 'border-[var(--accent)] bg-[var(--accent)]/5 ring-1 ring-[var(--accent)] shadow-[0_0_15px_rgba(var(--accent-rgb),0.1)]'
                                        : 'border-[var(--border)] hover:border-[var(--accent)]/40 hover:bg-[var(--surface-elevated)]'
                                        }`}
                                >
                                    <div>
                                        <div className={`font-medium text-sm transition-colors ${value === opt.id ? 'text-[var(--accent)]' : ''}`}>{opt.label}</div>
                                        <div className="text-xs text-[var(--muted)]/80">{opt.desc}</div>
                                    </div>
                                    {value === opt.id && (
                                        <div className="w-2 h-2 rounded-full bg-[var(--accent)] shadow-sm animate-scale-in" />
                                    )}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Lines Selector */}
                    <div className="flex-1 min-w-[200px]">
                        <label className="block text-sm font-medium text-[var(--muted)] mb-3">
                            Max Lines
                        </label>
                        {disableMaxLines ? (
                            /* Disabled state for Standard model */
                            <div className="p-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface)]/50">
                                <div className="flex items-center gap-2 mb-2">
                                    <span className="text-lg">🎯</span>
                                    <span className="font-medium text-sm text-[var(--muted)]">Auto (Sync Priority)</span>
                                </div>
                                <p className="text-xs text-[var(--muted)]/70">
                                    Standard model prioritizes audio sync over line limits for accuracy.
                                </p>
                            </div>
                        ) : (
                            <div className="flex flex-col gap-2">
                                {lineOptions.map((opt) => (
                                    <button
                                        key={opt.value}
                                        onClick={handleLineChange(opt.value)}
                                        className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between group ${lines === opt.value
                                            ? 'border-[var(--accent)] bg-[var(--accent)]/5 ring-1 ring-[var(--accent)] shadow-[0_0_15px_rgba(var(--accent-rgb),0.1)]'
                                            : 'border-[var(--border)] hover:border-[var(--accent)]/40 hover:bg-[var(--surface-elevated)]'
                                            }`}
                                    >
                                        <div>
                                            <div className={`font-medium text-sm transition-colors ${lines === opt.value ? 'text-[var(--accent)]' : ''}`}>{opt.label}</div>
                                            <div className="text-xs text-[var(--muted)]/80">{opt.desc}</div>
                                        </div>
                                        {lines === opt.value && (
                                            <div className="w-2 h-2 rounded-full bg-[var(--accent)] shadow-sm animate-scale-in" />
                                        )}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Style / Color Selector */}
                    {colors && onChangeColor && (
                        <div className="flex-1 min-w-[200px]">
                            <label className="block text-sm font-medium text-[var(--muted)] mb-3">
                                Subtitle Style
                            </label>
                            <div className="flex flex-col gap-2">
                                {colors.map((c) => (
                                    <button
                                        key={c.value}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onChangeColor(c.value);
                                        }}
                                        className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between group ${subtitleColor === c.value
                                            ? 'border-[var(--accent)] bg-[var(--accent)]/5 ring-1 ring-[var(--accent)] shadow-[0_0_15px_rgba(var(--accent-rgb),0.1)]'
                                            : 'border-[var(--border)] hover:border-[var(--accent)]/40 hover:bg-[var(--surface-elevated)]'
                                            }`}
                                    >
                                        <div className="flex items-center gap-3">
                                            <div
                                                className={`w-4 h-4 rounded-full border border-black/10 shadow-sm transition-transform ${subtitleColor === c.value ? 'scale-110 ring-2 ring-offset-1 ring-[var(--accent)]' : ''}`}
                                                style={{ backgroundColor: c.value }}
                                            />
                                            <div className={`font-medium text-sm transition-colors ${subtitleColor === c.value ? 'text-[var(--accent)]' : ''}`}>
                                                {c.label}
                                            </div>
                                        </div>
                                        {subtitleColor === c.value && (
                                            <div className="w-2 h-2 rounded-full bg-[var(--accent)] shadow-sm animate-scale-in" />
                                        )}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
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
                                    className="absolute inset-0 w-full h-full object-cover opacity-100"
                                />

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
                            {Array.from({ length: lines === 0 ? 1 : lines }).map((_, i) => (
                                <div
                                    key={i}
                                    className={`h-3 rounded-sm shadow-lg w-full flex items-center justify-center opacity-90 animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-backwards ${!previewColor ? 'bg-[var(--accent)]/60' : ''}`}
                                    style={{
                                        width: `${85 - (i * 10)}%`, // Taper width for visual effect
                                        animationDelay: `${i * 50}ms`,
                                        backgroundColor: previewColor ? previewColor : undefined,
                                        boxShadow: previewColor ? `0 2px 4px ${previewColor}40` : undefined
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
