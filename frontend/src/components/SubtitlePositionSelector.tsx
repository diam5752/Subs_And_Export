import React, { useCallback, useId } from 'react';
import { useI18n } from '@/context/I18nContext';

export interface SubtitlePositionSelectorProps {
    value: number;  // 5-35 (percentage from bottom)
    onChange: (value: number) => void;
    lines: number;
    onChangeLines: (lines: number) => void;
    thumbnailUrl?: string | null;
    previewColor?: string;
    disableMaxLines?: boolean;
    subtitleSize?: number;  // 50-150 scale (percentage)
    onChangeSize?: (size: number) => void;
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
    subtitleSize = 100,  // Default 100%
    onChangeSize,
    karaokeEnabled = true,
    onChangeKaraoke,
    karaokeSupported = false
}: SubtitlePositionSelectorProps & { subtitleColor?: string, onChangeColor?: (color: string) => void, colors?: Array<{ label: string; value: string; ass: string }> }) {
    const { t } = useI18n();
    const colorLabelId = useId();
    const sizeLabelId = useId();
    const karaokeLabelId = useId();
    const linesLabelId = useId();

    // Map numeric position (5-35) to CSS 'bottom' percentage for preview
    const getPreviewBottom = (pos: number) => {
        return `${pos}%`;
    };



    // Preset tick marks for position
    const positionPresets = [
        { value: 6, label: t('positionLow') },
        { value: 16, label: t('positionMiddle') },
        { value: 45, label: t('positionHigh') },
    ];

    // Preset tick marks for size
    const sizePresets = [
        { value: 70, label: t('sizeSmall') },
        { value: 85, label: t('sizeMedium') },
        { value: 100, label: t('sizeBig') },
        { value: 150, label: t('sizeExtraBig') },
    ];

    const handleLineChange = useCallback((num: number) => (e: React.MouseEvent) => {
        e.stopPropagation();
        onChangeLines(num);
    }, [onChangeLines]);

    const lineOptions = [
        { value: 0, label: t('lines1Word'), desc: t('lines1WordDesc') },
        { value: 1, label: t('linesSingle'), desc: t('linesSingleDesc') },
        { value: 2, label: t('linesDouble'), desc: t('linesDoubleDesc') },
        { value: 3, label: t('linesThree'), desc: t('linesThreeDesc') },
    ];

    return (
        <div className="space-y-6">
            <div className="flex flex-col xl:flex-row gap-8">
                {/* Controls Area */}
                <div className="flex-1 space-y-6">
                    {/* Top Row: Size & Lines */}
                    <div className="flex flex-col sm:flex-row gap-4">
                        {/* Size Slider */}
                        {onChangeSize && (
                            <div className="flex-1 min-w-[200px]">
                                <label htmlFor={sizeLabelId} className="block text-sm font-medium text-[var(--muted)] mb-3">
                                    {t('sizeLabel')}
                                </label>
                                <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)]">
                                    {/* Size Preview Text */}
                                    <div className="flex items-center justify-center mb-4">
                                        <span
                                            className="font-bold text-[var(--foreground)] transition-all duration-200"
                                            style={{ fontSize: `${Math.max(14, subtitleSize * 0.28)}px` }}
                                            aria-hidden="true"
                                        >
                                            Aa
                                        </span>
                                    </div>

                                    {/* Slider */}
                                    <div className="relative">
                                        <input
                                            id={sizeLabelId}
                                            type="range"
                                            min={50}
                                            max={150}
                                            value={subtitleSize}
                                            onChange={(e) => {
                                                e.stopPropagation();
                                                onChangeSize(Number(e.target.value));
                                            }}
                                            onClick={(e) => e.stopPropagation()}
                                            className="w-full h-2 rounded-full appearance-none cursor-pointer bg-[var(--border)]
                                                [&::-webkit-slider-thumb]:appearance-none
                                                [&::-webkit-slider-thumb]:w-5
                                                [&::-webkit-slider-thumb]:h-5
                                                [&::-webkit-slider-thumb]:rounded-full
                                                [&::-webkit-slider-thumb]:bg-[var(--accent)]
                                                [&::-webkit-slider-thumb]:shadow-lg
                                                [&::-webkit-slider-thumb]:cursor-pointer
                                                [&::-webkit-slider-thumb]:transition-transform
                                                [&::-webkit-slider-thumb]:hover:scale-110
                                                [&::-moz-range-thumb]:w-5
                                                [&::-moz-range-thumb]:h-5
                                                [&::-moz-range-thumb]:rounded-full
                                                [&::-moz-range-thumb]:bg-[var(--accent)]
                                                [&::-moz-range-thumb]:border-0
                                                [&::-moz-range-thumb]:shadow-lg
                                                [&::-moz-range-thumb]:cursor-pointer"
                                            style={{
                                                background: `linear-gradient(to right, var(--accent) 0%, var(--accent) ${((subtitleSize - 50) / 100) * 100}%, var(--border) ${((subtitleSize - 50) / 100) * 100}%, var(--border) 100%)`
                                            }}
                                        />

                                        {/* Preset Tick Marks */}
                                        <div className="flex justify-between mt-2 px-1">
                                            {sizePresets.map((preset) => (
                                                <button
                                                    key={preset.value}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        onChangeSize(preset.value);
                                                    }}
                                                    className={`text-[10px] px-1.5 py-0.5 rounded transition-all ${subtitleSize === preset.value
                                                        ? 'text-[var(--accent)] font-medium'
                                                        : 'text-[var(--muted)] hover:text-[var(--foreground)]'
                                                        }`}
                                                >
                                                    {preset.label}
                                                </button>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Position Slider - Under Size */}
                                    <div className="mt-4 pt-4 border-t border-[var(--border)]">
                                        {/* Centered Mini phone preview - like the Aa preview above */}
                                        <div className="flex items-center justify-center mb-4">
                                            <div className="relative w-8 h-14 bg-slate-700/50 rounded-lg border border-slate-600/50 overflow-hidden">
                                                {/* Subtitle line indicator */}
                                                <div
                                                    className="absolute left-1 right-1 h-1 bg-[var(--accent)] rounded-full transition-all duration-200 shadow-[0_0_6px_var(--accent)]"
                                                    style={{ bottom: `${((value - 5) / 45) * 70 + 10}%` }}
                                                />
                                            </div>
                                        </div>

                                        {/* Slider */}
                                        <div className="relative">
                                            <input
                                                aria-label={t('positionLabel') || 'Subtitle Position'}
                                                type="range"
                                                min={5}
                                                max={50}
                                                value={value}
                                                aria-label={t('positionLabel')}
                                                onChange={(e) => {
                                                    e.stopPropagation();
                                                    onChange(Number(e.target.value));
                                                }}
                                                onClick={(e) => e.stopPropagation()}
                                                className="w-full h-2 rounded-full appearance-none cursor-pointer bg-[var(--border)]
                                                    [&::-webkit-slider-thumb]:appearance-none
                                                    [&::-webkit-slider-thumb]:w-5
                                                    [&::-webkit-slider-thumb]:h-5
                                                    [&::-webkit-slider-thumb]:rounded-full
                                                    [&::-webkit-slider-thumb]:bg-[var(--accent)]
                                                    [&::-webkit-slider-thumb]:shadow-lg
                                                    [&::-webkit-slider-thumb]:cursor-pointer
                                                    [&::-webkit-slider-thumb]:transition-transform
                                                    [&::-webkit-slider-thumb]:hover:scale-110
                                                    [&::-moz-range-thumb]:w-5
                                                    [&::-moz-range-thumb]:h-5
                                                    [&::-moz-range-thumb]:rounded-full
                                                    [&::-moz-range-thumb]:bg-[var(--accent)]
                                                    [&::-moz-range-thumb]:border-0
                                                    [&::-moz-range-thumb]:shadow-lg
                                                    [&::-moz-range-thumb]:cursor-pointer"
                                                style={{
                                                    background: `linear-gradient(to right, var(--accent) 0%, var(--accent) ${((value - 5) / 45) * 100}%, var(--border) ${((value - 5) / 45) * 100}%, var(--border) 100%)`
                                                }}
                                            />
                                            {/* Preset Tick Marks */}
                                            <div className="flex justify-between mt-2 px-1">
                                                {positionPresets.map((preset) => (
                                                    <button
                                                        key={preset.value}
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            onChange(preset.value);
                                                        }}
                                                        className={`text-[10px] px-1.5 py-0.5 rounded transition-all ${value === preset.value
                                                            ? 'text-[var(--accent)] font-medium'
                                                            : 'text-[var(--muted)] hover:text-[var(--foreground)]'
                                                            }`}
                                                    >
                                                        {preset.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Lines Selector */}
                        <div className="flex-1 min-w-[200px]">
                            <label id={linesLabelId} className="block text-sm font-medium text-[var(--muted)] mb-3">
                                {t('maxLinesLabel')}
                            </label>
                            {disableMaxLines ? (
                                /* Disabled state for Standard model */
                                <div className="p-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface)]/50 h-full">
                                    <div className="flex items-center gap-2 mb-2">
                                        <span className="text-lg">🎯</span>
                                        <span className="font-medium text-sm text-[var(--muted)]">{t('linesAuto')}</span>
                                    </div>
                                    <p className="text-xs text-[var(--muted)]/70">
                                        {t('linesAutoDesc')}
                                    </p>
                                </div>
                            ) : (
                                <div className="flex flex-col gap-2" role="group" aria-labelledby={linesLabelId}>
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

                    {/* Bottom Row: Style & Karaoke */}
                    <div className="flex flex-col sm:flex-row gap-4">

                        {colors && onChangeColor && (
                            <div className="flex-1">
                                <label id={colorLabelId} className="block text-sm font-medium text-[var(--muted)] mb-3">
                                    {t('colorLabel')}
                                </label>
                                <div
                                    className="flex items-center gap-3 p-3 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)]"
                                    role="radiogroup"
                                    aria-labelledby={colorLabelId}
                                >
                                    {/* Color Swatches */}
                                    {colors.map((c) => (
                                        <button
                                            key={c.value}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onChangeColor(c.value);
                                            }}
                                            className="group relative"
                                            title={c.label}
                                            role="radio"
                                            aria-checked={subtitleColor === c.value}
                                            aria-label={c.label}
                                        >
                                            <div
                                                className={`w-8 h-8 rounded-full border-2 shadow-md transition-all ${subtitleColor === c.value
                                                    ? 'border-white scale-110 ring-2 ring-white/30'
                                                    : 'border-transparent hover:scale-105 hover:border-white/30'
                                                    }`}
                                                style={{ backgroundColor: c.value }}
                                            />
                                            {subtitleColor === c.value && (
                                                <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-white" />
                                            )}
                                        </button>
                                    ))}
                                    {/* Selected label */}
                                    <span className="ml-2 text-sm text-[var(--muted)]">
                                        {colors.find(c => c.value === subtitleColor)?.label || t('colorSelect')}
                                    </span>
                                </div>
                            </div>
                        )}

                        {/* Karaoke Toggle (separate column, next to colors) */}
                        {onChangeKaraoke && karaokeSupported && (
                            <div className="flex-1 min-w-[200px]">
                                <label id={karaokeLabelId} className="block text-sm font-medium text-[var(--muted)] mb-3">
                                    {t('karaokeLabel')}
                                </label>
                                <button
                                    role="switch"
                                    aria-checked={karaokeEnabled}
                                    aria-labelledby={karaokeLabelId}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onChangeKaraoke(!karaokeEnabled);
                                    }}
                                    role="switch"
                                    aria-checked={karaokeEnabled}
                                    aria-labelledby={karaokeLabelId}
                                    className={`w-full p-3 rounded-xl border text-left transition-all flex items-center justify-between group relative overflow-hidden ${karaokeEnabled
                                        ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                                        : 'border-[var(--border)] hover:border-[var(--border-hover)] bg-[var(--surface-elevated)]'
                                        }`}
                                >
                                    <div className="flex items-center gap-3">
                                        <div className={`p-1.5 rounded-lg ${karaokeEnabled ? 'bg-[var(--accent)] text-[#031018]' : 'bg-[var(--surface)] text-[var(--muted)]'}`}>
                                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                                            </svg>
                                        </div>
                                        <div>
                                            <div className={`font-medium text-sm transition-colors ${karaokeEnabled ? 'text-[var(--accent)]' : ''}`}>{t('karaokeMode')}</div>
                                            <div className="text-xs text-[var(--muted)]/80">{karaokeEnabled ? t('karaokeActive') : t('karaokeStatic')}</div>
                                        </div>
                                    </div>
                                    {/* iOS style toggle switch */}
                                    <div className={`w-10 h-6 rounded-full transition-colors relative ${karaokeEnabled ? 'bg-[var(--accent)]' : 'bg-[var(--border)]'}`}>
                                        <div className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${karaokeEnabled ? 'translate-x-4' : ''}`} />
                                    </div>
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                {/* Visual Preview - Phone Mockup */}
                <div className="flex-shrink-0 flex flex-col items-center pt-2">
                    <div className="mb-4 text-center">
                        <h4 className="text-sm font-semibold text-[var(--foreground)] uppercase tracking-wide mb-1">
                            {t('previewWindowLabel')}
                        </h4>
                        <p className="text-[10px] text-[var(--muted)] max-w-[160px] leading-tight">
                            {t('previewWindowDesc')}
                        </p>
                    </div>

                    {/* Phone Mockup */}
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

                        {/* Subtitle Text - Real text preview */}
                        <div
                            key={`subtitle-preview-${lines}`}
                            className="absolute left-3 right-3 flex flex-col gap-0.5 items-center transition-all duration-300 ease-out"
                            style={{
                                bottom: getPreviewBottom(value),
                            }}
                        >
                            {lines === 0 ? (
                                /* Single word mode - one big word */
                                <div
                                    className="font-bold uppercase tracking-wide animate-in fade-in slide-in-from-bottom-2 duration-300"
                                    style={{
                                        fontSize: `${Math.max(10, subtitleSize * 0.16)}px`,
                                        color: previewColor || '#FFFFFF',
                                        textShadow: '2px 2px 4px rgba(0,0,0,0.8), 0 0 10px rgba(0,0,0,0.5)',
                                        letterSpacing: '0.05em',
                                    }}
                                >
                                    {t('previewWord') || 'WATCH'}
                                </div>
                            ) : (
                                /* Multi-line mode */
                                <>
                                    <div
                                        className="font-bold uppercase tracking-wide text-center animate-in fade-in slide-in-from-bottom-2 duration-300"
                                        style={{
                                            fontSize: `${Math.max(8, subtitleSize * 0.11)}px`,
                                            color: previewColor || '#FFFFFF',
                                            textShadow: '1px 1px 3px rgba(0,0,0,0.8), 0 0 8px rgba(0,0,0,0.5)',
                                            letterSpacing: '0.03em',
                                        }}
                                    >
                                        {t('previewLine1') || 'THIS IS HOW YOUR'}
                                    </div>
                                    {lines >= 2 && (
                                        <div
                                            className="font-bold uppercase tracking-wide text-center animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-backwards"
                                            style={{
                                                fontSize: `${Math.max(8, subtitleSize * 0.11)}px`,
                                                color: previewColor || '#FFFFFF',
                                                textShadow: '1px 1px 3px rgba(0,0,0,0.8), 0 0 8px rgba(0,0,0,0.5)',
                                                letterSpacing: '0.03em',
                                                animationDelay: '50ms',
                                            }}
                                        >
                                            {t('previewLine2') || 'SUBTITLES LOOK'}
                                        </div>
                                    )}
                                    {lines >= 3 && (
                                        <div
                                            className="font-bold uppercase tracking-wide text-center animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-backwards"
                                            style={{
                                                fontSize: `${Math.max(8, subtitleSize * 0.11)}px`,
                                                color: previewColor || '#FFFFFF',
                                                textShadow: '1px 1px 3px rgba(0,0,0,0.8), 0 0 8px rgba(0,0,0,0.5)',
                                                letterSpacing: '0.03em',
                                                animationDelay: '100ms',
                                            }}
                                        >
                                            {t('previewLine3') || 'ON YOUR VIDEO'}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
