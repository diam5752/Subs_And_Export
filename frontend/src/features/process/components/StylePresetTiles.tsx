import React, { memo } from 'react';
import { useI18n } from '@/context/I18nContext';

const SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR: Record<string, string> = {
    '#FFFF00': 'bg-[#FFFF00]',
    '#FFFFFF': 'bg-[#FFFFFF]',
    '#00FFFF': 'bg-[#00FFFF]',
    '#00FF00': 'bg-[#00FF00]',
    '#FF00FF': 'bg-[#FF00FF]',
};

function getSubtitlePreviewBgClass(color: string): string {
    const normalized = color.trim().toUpperCase();
    return SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR[normalized] ?? SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR['#FFFF00'];
}

function getPreviewBottomClass(position: number | string): string {
    const numericPosition = typeof position === 'number' ? position : Number(position);

    if (!Number.isNaN(numericPosition)) {
        if (numericPosition >= 40) return 'bottom-[80%]';
        if (numericPosition <= 15) return 'bottom-[20%]';
        return 'bottom-[50%]';
    }

    if (position === 'top') return 'bottom-[80%]';
    if (position === 'bottom') return 'bottom-[20%]';
    return 'bottom-[50%]';
}

export interface StylePreset {
    id: string;
    name: string;
    description: string;
    emoji: string;
    settings: {
        position: number;
        size: number;
        lines: number;
        color: string;
        karaoke: boolean;
    };
    colorClass: string;
}

export interface LastUsedSettings {
    position: number;
    size: number;
    lines: number;
    color: string;
    karaoke: boolean;
    timestamp: number;
}

interface StylePresetTilesProps {
    presets: StylePreset[];
    activePreset: string | null;
    lastUsedSettings: LastUsedSettings | null;
    onSelectPreset: (preset: StylePreset) => void;
    onSelectLastUsed: () => void;
}

export const StylePresetTiles = memo(({
    presets,
    activePreset,
    lastUsedSettings,
    onSelectPreset,
    onSelectLastUsed
}: StylePresetTilesProps) => {
    const { t } = useI18n();

    return (
        <div
            className="grid grid-cols-2 gap-3 mb-6"
            role="radiogroup"
            aria-label={t('tabStyles') || 'Style Presets'}
        >
            {presets.map((preset) => {
                return (
                    <button
                        key={preset.id}
                        role="radio"
                        aria-checked={activePreset === preset.id}
                        aria-label={preset.name}
                        onClick={(e) => {
                            e.stopPropagation();
                            onSelectPreset(preset);
                        }}
                        className={`p-3 rounded-xl border text-left transition-all relative overflow-hidden group flex flex-row gap-3 items-center ${activePreset === preset.id
                            ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]'
                            : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                            } `}
                    >
                        <div className={`absolute inset-0 bg-gradient-to-br ${preset.colorClass} opacity-10`} />
                        <div className="flex-shrink-0 w-10 aspect-[9/16] bg-slate-900 rounded-lg border border-slate-600 overflow-hidden relative shadow-lg">
                            <div className="absolute top-1 left-1/2 -translate-x-1/2 w-4 h-1 bg-slate-700 rounded-full" />
                            <div className="absolute inset-0 bg-gradient-to-b from-slate-800/50 to-black/60" />
                            <div className={`absolute left-1 right-1 flex flex-col gap-[1px] items-center ${getPreviewBottomClass(preset.settings.position)}`}>
                                <div className={`h-[2px] w-[75%] rounded-full ${getSubtitlePreviewBgClass(preset.settings.color)}`} />
                                {preset.settings.lines > 1 && (
                                    <div className={`h-[2px] w-[55%] rounded-full ${getSubtitlePreviewBgClass(preset.settings.color)}`} />
                                )}
                            </div>
                            <div className="absolute bottom-1 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-slate-600 rounded-full" />
                        </div>
                        <div className="flex-1 min-w-0 relative">
                            <div className="flex items-center gap-1.5 mb-0.5">
                                <span className="text-sm">{preset.emoji}</span>
                                <span className="font-semibold text-xs truncate">{preset.name}</span>
                            </div>
                            <p className="text-[10px] text-[var(--muted)] leading-tight line-clamp-2">{preset.description}</p>
                        </div>
                        {activePreset === preset.id && (
                            <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-[var(--accent)] flex items-center justify-center animate-scale-in">
                                <svg className="w-2.5 h-2.5 text-[#031018]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                </svg>
                            </div>
                        )}
                    </button>
                );
            })}

            {/* Last Used Tile */}
            <button
                role="radio"
                aria-checked={activePreset === 'lastUsed'}
                aria-label={t('styleLastUsedName') || 'Last Used'}
                aria-disabled={!lastUsedSettings}
                onClick={(e) => {
                    e.stopPropagation();
                    if (!lastUsedSettings) return;
                    onSelectLastUsed();
                }}
                className={`p-3 rounded-xl border text-left transition-all relative overflow-hidden group flex flex-row gap-3 items-center ${activePreset === 'lastUsed'
                    ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]'
                    : !lastUsedSettings
                        ? 'border-[var(--border)] opacity-50 grayscale cursor-not-allowed'
                        : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                    } `}
                disabled={!lastUsedSettings}
            >
                <div className="absolute inset-0 bg-gradient-to-br from-emerald-500 to-teal-600 opacity-10" />
                <div className="flex-shrink-0 w-10 aspect-[9/16] bg-slate-900 rounded-lg border border-slate-600 overflow-hidden relative shadow-lg">
                    <div className="absolute top-1 left-1/2 -translate-x-1/2 w-4 h-1 bg-slate-700 rounded-full" />
                    <div className="absolute inset-0 bg-gradient-to-b from-slate-800/50 to-black/60" />
                    {lastUsedSettings ? (
                        <>
                            <div className={`absolute left-1 right-1 flex flex-col gap-[1px] items-center ${getPreviewBottomClass(lastUsedSettings.position)}`}>
                                <div className={`h-[2px] w-[75%] rounded-full ${getSubtitlePreviewBgClass(lastUsedSettings.color)}`} />
                                {lastUsedSettings.lines > 1 && (
                                    <div className={`h-[2px] w-[55%] rounded-full ${getSubtitlePreviewBgClass(lastUsedSettings.color)}`} />
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="absolute inset-0 flex items-center justify-center">
                            <svg className="w-4 h-4 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                        </div>
                    )}
                    <div className="absolute bottom-1 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-slate-600 rounded-full" />
                </div>
                <div className="flex-1 min-w-0 relative">
                    <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-sm">🕐</span>
                        <span className="font-semibold text-xs truncate">{t('styleLastUsedName') || 'Last Used'}</span>
                    </div>
                    <p className="text-[10px] text-[var(--muted)] leading-tight line-clamp-2">
                        {lastUsedSettings ? (t('styleLastUsedDesc') || 'Your most recent settings') : (t('styleLastUsedNoHistory') || 'No previous exports yet')}
                    </p>
                </div>
                {activePreset === 'lastUsed' && (
                    <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-[var(--accent)] flex items-center justify-center animate-scale-in">
                        <svg className="w-2.5 h-2.5 text-[#031018]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                    </div>
                )}
            </button>
        </div>
    );
});

StylePresetTiles.displayName = 'StylePresetTiles';
