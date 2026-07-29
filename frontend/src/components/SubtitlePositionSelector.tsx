'use client';

import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useI18n } from '@/context/I18nContext';
import { InfoTooltip } from '@/components/InfoTooltip';

// Constants moved outside component
const MORE_COLORS = [
    { value: '#FF0000', label: 'Red' },
    { value: '#FF7F00', label: 'Orange' },
    { value: '#FFFF00', label: 'Yellow' },
    { value: '#7FFF00', label: 'Chartreuse' },
    { value: '#00FF00', label: 'Green' },
    { value: '#00FF7F', label: 'Spring Green' },
    { value: '#00FFFF', label: 'Cyan' },
    { value: '#007FFF', label: 'Azure' },
    { value: '#0000FF', label: 'Blue' },
    { value: '#7F00FF', label: 'Violet' },
    { value: '#FF00FF', label: 'Magenta' },
    { value: '#FF007F', label: 'Rose' },
    { value: '#FFFFFF', label: 'White' },
    { value: '#C0C0C0', label: 'Silver' },
    { value: '#808080', label: 'Gray' },
    { value: '#000000', label: 'Black' }
];


interface SubtitlePositionSelectorProps {
    lines: number;
    onChangeLines: (lines: number) => void;
    subtitleSize: number;
    onChangeSize: (size: number) => void;
    subtitleColor: string;
    onChangeColor: (color: string) => void;
    colors: Array<{ label: string; value: string; ass: string }>;
}

export const SubtitlePositionSelector = React.memo<SubtitlePositionSelectorProps>(({
    lines,
    onChangeLines,
    subtitleColor,
    onChangeColor,
    colors,
    subtitleSize,
    onChangeSize,
}) => {
    const { t } = useI18n();
    const colorLabelId = useId();
    const sizeLabelId = useId();
    const linesLabelId = useId();

    const [showColorGrid, setShowColorGrid] = useState(false);
    const gridRef = useRef<HTMLDivElement>(null);

    // Close color grid when clicking outside
    useEffect(() => {
        function handleClickOutside(event: MouseEvent) {
            if (gridRef.current && !gridRef.current.contains(event.target as Node)) {
                setShowColorGrid(false);
            }
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
        };
    }, []);

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
                <div className="editor-style-controls-layout flex-1">
                    {/* Top Row: Size & Lines */}
                    <div className="editor-style-primary-row">
                        {/* Size Slider */}
                        <div
                            className="editor-style-size-control min-w-[200px]"
                            data-testid="style-size-control"
                        >
                                <div className="flex items-center gap-2 mb-3">
                                    <label htmlFor={sizeLabelId} className="block text-sm font-medium text-[var(--muted)]">
                                        {t('sizeLabel')}
                                    </label>
                                    <InfoTooltip ariaLabel={`${t('infoPrefix')} ${t('sizeLabel')}`}>
                                        <div className="space-y-2">
                                            <div className="font-semibold text-[11px]">{t('sizeLabel')}</div>
                                            <p className="text-[var(--muted)] leading-snug">{t('tooltipSizeDesc')}</p>
                                            <div className="flex items-end justify-between gap-3 rounded-lg border border-white/10 bg-black/20 p-2">
                                                <span aria-hidden="true" className="text-[10px] font-bold text-white/70">
                                                    Aa
                                                </span>
                                                <span aria-hidden="true" className="text-base font-black text-white">
                                                    Aa
                                                </span>
                                            </div>
                                        </div>
                                    </InfoTooltip>
                                </div>
                                <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)]">
                                    {/* Size Preview Text */}
                                    <div className="flex items-center justify-center mb-4">
                                        <span
                                            className="font-bold text-[var(--foreground)]"
                                            style={{ fontSize: '24px' }}
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

                                </div>
                            </div>

                        {/* Lines Selector */}
                        <div
                            className="editor-style-lines-control min-w-[200px]"
                            data-testid="style-lines-control"
                        >
                            <div className="flex items-center gap-2 mb-3">
                                <label id={linesLabelId} className="block text-sm font-medium text-[var(--muted)]">
                                    {t('maxLinesLabel')}
                                </label>
                                <InfoTooltip ariaLabel={`${t('infoPrefix')} ${t('maxLinesLabel')}`}>
                                    <div className="space-y-2">
                                        <div className="font-semibold text-[11px]">{t('maxLinesLabel')}</div>
                                        <p className="text-[var(--muted)] leading-snug">{t('tooltipMaxLinesDesc')}</p>
                                        <div className="rounded-lg border border-white/10 bg-black/20 p-2">
                                            <div className="space-y-1">
                                                <div className="h-1.5 w-full rounded-full bg-[var(--accent)]/50" />
                                                <div className="h-1.5 w-4/5 rounded-full bg-[var(--accent)]/35" />
                                                <div className="h-1.5 w-3/5 rounded-full bg-white/10" />
                                            </div>
                                        </div>
                                    </div>
                                </InfoTooltip>
                            </div>
                            <div
                                className="editor-style-lines-options flex flex-col gap-2"
                                role="radiogroup"
                                aria-labelledby={linesLabelId}
                            >
                                {lineOptions.map((opt) => (
                                    <button
                                        key={opt.value}
                                        role="radio"
                                        aria-checked={lines === opt.value}
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
                        </div>
                    </div>

                    {/* Middle Row: Colors */}
                    <div
                        className="editor-style-color-control w-full"
                        data-testid="style-color-control"
                    >
                            <div className="flex items-center gap-2 mb-3">
                                <label id={colorLabelId} className="block text-sm font-medium text-[var(--muted)]">
                                    {t('colorLabel')}
                                </label>
                                <InfoTooltip ariaLabel={`${t('infoPrefix')} ${t('colorLabel')}`}>
                                    <div className="space-y-2">
                                        <div className="font-semibold text-[11px]">{t('colorLabel')}</div>
                                        <p className="text-[var(--muted)] leading-snug">{t('tooltipColorDesc')}</p>
                                        <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/20 p-2">
                                            <span aria-hidden="true" className="h-3.5 w-3.5 rounded-full bg-[#FFFF00] border border-white/10" />
                                            <span aria-hidden="true" className="h-3.5 w-3.5 rounded-full bg-[#8B5CF6] border border-white/10" />
                                            <span aria-hidden="true" className="h-3.5 w-3.5 rounded-full bg-[#00FFFF] border border-white/10" />
                                        </div>
                                    </div>
                                </InfoTooltip>
                            </div>
                            <div
                                className="editor-style-color-surface flex min-w-0 items-center rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] p-3 min-h-[88px]"
                                role="radiogroup"
                                aria-labelledby={colorLabelId}
                            >
                                {/* Color Swatches */}
                                <div
                                    className="editor-style-color-options relative"
                                    data-testid="style-color-options"
                                    ref={gridRef}
                                >
                                    {/* First 3 Presets */}
                                    {colors.slice(0, 3).map((c) => (
                                        <button
                                            key={c.value}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onChangeColor(c.value);
                                                setShowColorGrid(false);
                                            }}
                                            className="editor-style-color-swatch group relative transition-transform active:scale-95"
                                            title={c.label}
                                            role="radio"
                                            aria-checked={subtitleColor === c.value}
                                            aria-label={c.label}
                                        >
                                            <div
                                                className={`editor-style-color-dot rounded-full border-2 shadow-sm transition-all duration-300 ease-out ${subtitleColor === c.value
                                                    ? 'border-white scale-110 ring-2 ring-white/20'
                                                    : 'border-transparent hover:scale-110 hover:border-white/30 opacity-80 hover:opacity-100'
                                                    }`}
                                                style={{ backgroundColor: c.value }}
                                            />
                                        </button>
                                    ))}

                                    {/* More Colors Button (Toggle Popover) */}
                                    <div className="editor-style-color-more">
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setShowColorGrid(!showColorGrid);
                                            }}
                                            className="editor-style-color-swatch group relative transition-transform active:scale-95"
                                            title={t('moreColors') || "More Colors"}
                                            aria-expanded={showColorGrid}
                                            aria-haspopup="true"
                                        >
                                            <div
                                                className={`editor-style-color-dot rounded-full border-2 shadow-md transition-all duration-300 ease-out flex items-center justify-center overflow-hidden bg-[var(--surface)] ${showColorGrid || !colors.slice(0, 3).some(c => c.value === subtitleColor)
                                                    ? 'border-white ring-2 ring-white/20'
                                                    : 'border-[var(--border)] hover:scale-110 hover:border-white/30'
                                                    }`}
                                            >
                                                {/* Conic Gradient Icon */}
                                                <div
                                                    className="w-full h-full opacity-80 group-hover:opacity-100 transition-opacity"
                                                    style={{
                                                        background: 'conic-gradient(from 180deg at 50% 50%, #FF0000 0deg, #00FF00 120deg, #0000FF 240deg, #FF0000 360deg)'
                                                    }}
                                                />

                                                {/* Plus Icon Overlay */}
                                                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                                                    <svg className="w-5 h-5 text-white drop-shadow-md" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                                                    </svg>
                                                </div>
                                            </div>
                                        </button>

                                        {/* Color Grid Popover */}
                                        {showColorGrid && (
                                            <div
                                                className="absolute right-0 top-full z-50 mt-3 w-[180px] max-w-[calc(100vw-2rem)] animate-in rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] p-3 shadow-2xl fade-in zoom-in-95 duration-200"
                                                role="radiogroup"
                                                aria-label={t('moreColors') || 'More Colors'}
                                            >
                                                <div className="grid grid-cols-4 gap-2">
                                                    {MORE_COLORS.map((color) => (
                                                        <button
                                                            key={color.value}
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                onChangeColor(color.value);
                                                                setShowColorGrid(false);
                                                            }}
                                                            className="w-8 h-8 rounded-full border border-white/10 hover:border-white hover:scale-110 transition-all shadow-sm relative focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:outline-none"
                                                            style={{ backgroundColor: color.value }}
                                                            title={color.label}
                                                            aria-label={color.label}
                                                            role="radio"
                                                            aria-checked={subtitleColor === color.value}
                                                        >
                                                            {subtitleColor === color.value && (
                                                                <div className="absolute inset-0 flex items-center justify-center">
                                                                    <div className="w-2 h-2 bg-black/40 rounded-full ring-1 ring-white/50" />
                                                                </div>
                                                            )}
                                                        </button>
                                                    ))}
                                                </div>
                                                {/* Triangle Pointer */}
                                                <div className="absolute -top-1.5 right-4 h-3 w-3 rotate-45 border-l border-t border-[var(--border)] bg-[var(--surface-elevated)]" />
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>

                </div>

            </div>
        </div>
    );
});

SubtitlePositionSelector.displayName = 'SubtitlePositionSelector';
