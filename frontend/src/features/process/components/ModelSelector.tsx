import React, { useMemo, useCallback } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext, TranscribeProvider, TranscribeMode } from '../ProcessContext';

export function ModelSelector() {
    const { t } = useI18n();
    const {
        AVAILABLE_MODELS,
        transcribeProvider,
        transcribeMode,
        setTranscribeProvider,
        setTranscribeMode,
        setHasChosenModel,
        setOverrideStep,
        onJobSelect,
        hasChosenModel,
        currentStep,
    } = useProcessContext();

    const modelGrid = useMemo(() => (
        <div
            role="radiogroup"
            aria-label={t('modelSelectTitle') || 'Pick a Model'}
            className={`grid grid-cols-1 sm:grid-cols-3 gap-3 transition-all duration-300 ${hasChosenModel ? 'opacity-100' : 'animate-slide-down'}`}
        >
            {AVAILABLE_MODELS.map((model) => {
                const isSelected = transcribeProvider === model.provider && transcribeMode === model.mode;

                const renderStat = (value: number, label: string, max: number = 5) => (
                    <div className="flex gap-0.5" role="meter" aria-label={`${label}: ${value} out of ${max}`} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
                        {Array.from({ length: max }).map((_, i) => (
                            <div
                                key={i}
                                className={`h-1.5 w-full rounded-full transition-colors ${i < value
                                    ? (isSelected ? 'bg-current opacity-80' : 'bg-[var(--foreground)] opacity-60')
                                    : 'bg-[var(--foreground)] opacity-20'
                                    } `}
                            />
                        ))}
                    </div>
                );

                return (
                    <button
                        key={model.id}
                        role="radio"
                        aria-checked={isSelected}
                        data-testid={`model-${model.provider === 'local' ? 'turbo' : model.provider}`}
                        onClick={(e) => {
                            e.stopPropagation();
                            setTranscribeProvider(model.provider as TranscribeProvider);
                            setTranscribeMode(model.mode as TranscribeMode);
                            setHasChosenModel(true);
                            setOverrideStep(2);
                            onJobSelect(null);

                            if (!isSelected) {
                                setTimeout(() => {
                                    document.getElementById('upload-section')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                }, 100);
                            }
                        }}
                        className={`p-4 rounded-xl border text-left transition-all duration-300 relative overflow-hidden group flex flex-col h-full ${isSelected
                            ? `${model.colorClass(true)} scale-[1.02] shadow-lg ring-1`
                            : hasChosenModel
                                ? 'border-[var(--border)] opacity-60 hover:opacity-100 hover:scale-[1.01] hover:bg-[var(--surface-elevated)] grayscale hover:grayscale-0'
                                : model.colorClass(false)
                            }`}
                    >
                        <div className="flex items-start justify-between mb-2 w-full">
                            {model.icon(isSelected)}
                            {isSelected && (
                                <div
                                    className={`w-5 h-5 rounded-full flex items-center justify-center ${model.provider === 'groq'
                                        ? 'bg-purple-500'
                                        : model.provider === 'whispercpp'
                                            ? 'bg-cyan-500'
                                            : 'bg-[var(--accent)]'
                                        }`}
                                >
                                    <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                    </svg>
                                </div>
                            )}
                        </div>
                        <div className="font-semibold text-base mb-1">{model.name}</div>
                        <div className="text-sm text-[var(--muted)] mb-4">{model.description}</div>

                        <div className="mt-auto space-y-2 mb-3">
                            <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statSpeed')}</span>
                                {renderStat(model.stats.speed, t('statSpeed'))}
                            </div>
                            <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statAccuracy')}</span>
                                {renderStat(model.stats.accuracy, t('statAccuracy'))}
                            </div>
                            <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statKaraoke')}</span>
                                <div className={`text-[10px] font-bold ${model.stats.karaoke ? 'text-emerald-500' : 'text-[var(--muted)]'} `}>
                                    {model.stats.karaoke ? t('statKaraokeSupported') : t('statKaraokeNo')}
                                </div>
                            </div>
                            <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statLines')}</span>
                                <div className={`text-[10px] font-bold ${model.stats.linesControl ? 'text-emerald-500' : 'text-cyan-400'} `}>
                                    {model.stats.linesControl ? t('statLinesCustom') : t('statLinesAuto')}
                                </div>
                            </div>
                        </div>

                        <div className="flex items-center gap-2 text-xs pt-3 border-t border-[var(--border)]/50">
                            <span className={`px-2 py-0.5 rounded-full font-medium ${model.badgeColor} `}>
                                {model.badge}
                            </span>
                        </div>
                    </button>
                );
            })}
        </div>
    ), [AVAILABLE_MODELS, transcribeProvider, transcribeMode, hasChosenModel, t, setTranscribeProvider, setTranscribeMode, setHasChosenModel, setOverrideStep, onJobSelect]);

    const handleStepClick = useCallback(() => {
        setOverrideStep(1);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }, [setOverrideStep]);

    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleStepClick();
        }
    }, [handleStepClick]);

    return useMemo(() => (
        <div className="card space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div
                    role="button"
                    tabIndex={0}
                    onKeyDown={handleKeyDown}
                    className={`flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 1 ? 'opacity-40 grayscale blur-[1px] hover:opacity-80 hover:grayscale-0 hover:blur-0' : 'opacity-100 scale-[1.01]'}`}
                    onClick={handleStepClick}
                >
                    <span className={`flex items-center justify-center px-4 py-1.5 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 ${currentStep === 1
                        ? 'bg-[var(--accent)] border-[var(--accent)] text-white shadow-[0_0_20px_2px_var(--accent)] scale-105 ring-2 ring-[var(--accent)]/30'
                        : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)] group-hover/step:border-[var(--accent)]/50 group-hover/step:text-[var(--accent)]'
                        }`}>STEP 1</span>
                    <div>
                        <h3 className="text-xl font-semibold">{t('modelSelectTitle') || 'Pick a Model'}</h3>
                        {!hasChosenModel && (
                            <p className="text-sm text-[var(--muted)] mt-1 ml-0.5">{t('modelSelectSubtitle')}</p>
                        )}
                    </div>
                </div>
                {hasChosenModel ? (
                    <span className="inline-flex items-center gap-2 text-xs font-semibold px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
                        <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                        {t('statusSynced') || 'Selected'}
                    </span>
                ) : (
                    <span className="inline-flex items-center gap-2 text-xs font-semibold px-3 py-1 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-200">
                        <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
                        {t('statusIdle') || 'Select to continue'}
                    </span>
                )}
            </div>

            {modelGrid}
        </div>
    ), [t, currentStep, hasChosenModel, modelGrid, handleStepClick, handleKeyDown]);
}
