import React, { useCallback } from 'react';

export interface SubtitlePositionSelectorProps {
    value: string;
    onChange: (value: string) => void;
    lines: number;
    onChangeLines: (lines: number) => void;
    thumbnailUrl?: string | null;
    previewColor?: string;
    disableMaxLines?: boolean;
    subtitleSize?: string;
    onChangeSize?: (size: string) => void;
    karaokeEnabled?: boolean;
    onChangeKaraoke?: (enabled: boolean) => void;
    karaokeSupported?: boolean;
}

export function SubtitlePositionSelector({
    value,
    onChange,
    lines,
    onChangeLines,
    thumbnailUrl,
    previewColor,
    subtitleColor,
    onChangeColor,
    colors,
    disableMaxLines,
    subtitleSize = 'medium',
    onChangeSize,
    karaokeEnabled = true,
    onChangeKaraoke,
    karaokeSupported = false
}: SubtitlePositionSelectorProps & { subtitleColor?: string, onChangeColor?: (color: string) => void, colors?: Array<{ label: string; value: string; ass: string }> }) {
    // Map position to CSS 'bottom' percentage for the preview
    // These are visual approximations to match the backend logic
    // Middle (default) ~= 16%
    // High (top) ~= 32% from bottom
    // Low (bottom) ~= 6%
    const getPreviewBottom = (pos: string) => {
        switch (pos) {
            case 'top': return '32%';
            case 'bottom': return '6%';
            default: return '16%';
        }
    };

    // Map size to scale for preview
    const getSizeScale = (size: string) => {
        switch (size) {
            case 'small': return 0.8;
            case 'big': return 1.3;
            default: return 1.0;
        }
    };

    const options = [
        { id: 'top', label: 'High', desc: 'Higher positioning' },
        { id: 'default', label: 'Middle', desc: 'Social Standard' },
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

    const sizeOptions = [
        { id: 'small', label: 'Small', desc: 'Subtle' },
        { id: 'medium', label: 'Medium', desc: 'Standard' },
        { id: 'big', label: 'Big', desc: 'Impactful' },
    ];

    return (
        <div className="space-y-6">
            <div className="flex flex-col xl:flex-row gap-8">
                {/* Controls Area */}
                <div className="flex-1 space-y-6">
                    {/* Top Row: Position & Lines */}
                    <div className="flex flex-col sm:flex-row gap-4">
                        {/* Position Selector */}
                        <div className="flex-1 min-w-[200px]">
                            <label className="block text-sm font-medium text-[var(--muted)] mb-3">
                                Position
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
                                <div className="p-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface)]/50 h-full">
                                    <div className="flex items-center gap-2 mb-2">
                                        <span className="text-lg">🎯</span>
                                        <span className="font-medium text-sm text-[var(--muted)]">Auto (Sync Priority)</span>
                                    </div>
                                    <p className="text-xs text-[var(--muted)]/70">
                                        Standard model prioritizes audio sync.
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
                    </div>

                    {/* Bottom Row: Size & Style */}
                    <div className="flex flex-col sm:flex-row gap-4">
                        {/* Size Selector */}
                        {onChangeSize && (
                            <div className="flex-1 min-w-[200px]">
                                <label className="block text-sm font-medium text-[var(--muted)] mb-3">
                                    Target Size
                                </label>
                                <div className="flex flex-col gap-2">
                                    {sizeOptions.map((opt) => (
                                        <button
                                            key={opt.id}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onChangeSize(opt.id);
                                            }}
                                            className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between group ${subtitleSize === opt.id
                                                ? 'border-[var(--accent)] bg-[var(--accent)]/5 ring-1 ring-[var(--accent)] shadow-[0_0_15px_rgba(var(--accent-rgb),0.1)]'
                                                : 'border-[var(--border)] hover:border-[var(--accent)]/40 hover:bg-[var(--surface-elevated)]'
                                                }`}
                                        >
                                            <div className="flex items-center gap-3">
                                                <div className="w-6 text-center text-[var(--foreground)] font-serif italic opacity-80" style={{ fontSize: opt.id === 'small' ? '0.8em' : opt.id === 'big' ? '1.4em' : '1.1em' }}>
                                                    Aa
                                                </div>
                                                <div>
                                                    <div className={`font-medium text-sm transition-colors ${subtitleSize === opt.id ? 'text-[var(--accent)]' : ''}`}>{opt.label}</div>
                                                    <div className="text-xs text-[var(--muted)]/80">{opt.desc}</div>
                                                </div>
                                            </div>
                                            {subtitleSize === opt.id && (
                                                <div className="w-2 h-2 rounded-full bg-[var(--accent)] shadow-sm animate-scale-in" />
                                            )}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Style / Color Selector */}
                        {colors && onChangeColor && (
                            <div className="flex-1 min-w-[200px]">
                                <label className="block text-sm font-medium text-[var(--muted)] mb-3">
                                    Style
                                </label>
                                <div className="flex flex-col gap-2">
                                    {/* Karaoke Toggle (only if supported) */}
                                    {onChangeKaraoke && karaokeSupported && (
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onChangeKaraoke(!karaokeEnabled);
                                            }}
                                            className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between group relative overflow-hidden ${karaokeEnabled
                                                ? 'border-emerald-500 bg-emerald-500/10 ring-1 ring-emerald-500'
                                                : 'border-[var(--border)] hover:border-[var(--border-hover)] bg-[var(--surface-elevated)]'
                                                }`}
                                        >
                                            <div className="flex items-center gap-3">
                                                <div className={`p-1.5 rounded-lg ${karaokeEnabled ? 'bg-emerald-500 text-white' : 'bg-[var(--surface)] text-[var(--muted)]'}`}>
                                                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                                                    </svg>
                                                </div>
                                                <div>
                                                    <div className={`font-medium text-sm transition-colors ${karaokeEnabled ? 'text-emerald-500' : ''}`}>Karaoke Mode</div>
                                                    <div className="text-xs text-[var(--muted)]/80">{karaokeEnabled ? 'Active words highlighted' : 'Standard static subtitles'}</div>
                                                </div>
                                            </div>
                                            {/* iOS style toggle switch */}
                                            <div className={`w-10 h-6 rounded-full transition-colors relative ${karaokeEnabled ? 'bg-emerald-500' : 'bg-[var(--border)]'}`}>
                                                <div className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${karaokeEnabled ? 'translate-x-4' : ''}`} />
                                            </div>
                                        </button>
                                    )}

                                    {/* Color Picker */}
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
                </div>

                {/* Visual Preview - Phone Mockup with optional video thumbnail */}
                <div className="flex-shrink-0 flex justify-center items-start pt-1">
                    <div className="relative w-[180px] h-[320px] bg-slate-800 rounded-[30px] border-[6px] border-slate-700 overflow-hidden shadow-2xl ring-1 ring-white/10">
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
                        <div className="absolute top-3 left-1/2 -translate-x-1/2 w-16 h-4 bg-black/60 rounded-full blur-[0.5px]" />

                        {/* Social Sidebar (Like/Comment/Share) */}
                        <div className="absolute bottom-20 right-3 w-7 flex flex-col gap-4 items-center">
                            <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                            <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                            <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                        </div>

                        {/* Social Bottom Info (username, caption) */}
                        <div className="absolute bottom-6 left-4 right-12 flex flex-col gap-2">
                            <div className="h-2.5 w-3/4 bg-white/30 rounded-full" />
                            <div className="h-2.5 w-1/2 bg-white/25 rounded-full" />
                        </div>

                        {/* Subtitle Bar - Animated with glow */}
                        {/* We render a bar per line to visualize stacking */}
                        <div
                            className="absolute left-4 right-4 flex flex-col gap-1.5 items-center transition-all duration-300 ease-out subtitle-preview-bar"
                            style={{
                                bottom: getPreviewBottom(value),
                            }}
                        >
                            {Array.from({ length: lines === 0 ? 1 : lines }).map((_, i) => (
                                <div
                                    key={i}
                                    className={`h-4 rounded-sm shadow-lg w-full flex items-center justify-center opacity-90 animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-backwards ${!previewColor ? 'bg-[var(--accent)]/60' : ''}`}
                                    style={{
                                        width: lines === 0 ? '45%' : `${90 - (i * 10)}%`, // Half width for 1-word mode, else taper
                                        transform: `scale(${getSizeScale(subtitleSize)})`,
                                        transformOrigin: 'center bottom',
                                        animationDelay: `${i * 50}ms`,
                                        backgroundColor: previewColor ? previewColor : undefined,
                                        boxShadow: previewColor ? `0 2px 4px ${previewColor}40` : undefined
                                    }}
                                >
                                    <div className="w-[90%] h-[3px] bg-white/80 rounded-full" />
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
