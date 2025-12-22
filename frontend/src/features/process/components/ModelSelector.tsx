import React, { useMemo, useCallback, useState, useEffect } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext, TranscribeProvider, TranscribeMode } from '../ProcessContext';
import { TokenIcon } from '@/components/icons';
import { formatPoints, processVideoCostForSelection } from '@/lib/points';

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
        hasChosenModel,
        currentStep,
        selectedJob,
    } = useProcessContext();

    // Local state to allow collapsing Step 1 even when it is active
    const [localCollapsed, setLocalCollapsed] = useState(false);

    // Reset local collapsed state when step changes
    useEffect(() => {
        if (currentStep !== 1) {
            setLocalCollapsed(false);
        }
    }, [currentStep]);

    // Collapsed state - expands automatically when on Step 1, unless manually collapsed
    const isExpanded = currentStep === 1 && !localCollapsed;

    // Get selected model for compact display
    const selectedModel = useMemo(() => {
        // 1. Current explicit selection
        const selected = AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode);
        if (selected) return selected;

        // 2. Fallback to current job's model if no explicit selection
        if (selectedJob?.result_data) {
            const jobProvider = selectedJob.result_data.transcribe_provider;
            const jobModelSize = selectedJob.result_data.model_size;
            const normalizedProvider = (jobProvider || '').toLowerCase();
            const normalizedModel = (jobModelSize || '').toLowerCase();
            const jobTier = normalizedModel === 'pro' || normalizedModel === 'standard'
                ? normalizedModel
                : normalizedModel.includes('turbo') || normalizedModel.includes('enhanced')
                    ? 'standard'
                    : normalizedModel.includes('large')
                        ? 'pro'
                        : normalizedProvider === 'openai' || normalizedModel.includes('ultimate') || normalizedModel.includes('whisper-1')
                            ? 'pro'
                            : 'standard';

            return AVAILABLE_MODELS.find(m => m.mode === jobTier);
        }
        return null;
    }, [AVAILABLE_MODELS, transcribeProvider, transcribeMode, selectedJob]);

    const scrollToUploadStep = useCallback(() => {
        const target = document.getElementById('step-2-wrapper');
        target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, []);

    const modelGrid = useMemo(() => (
        <div
            role="radiogroup"
            aria-label={t('modelSelectTitle') || 'Pick a Model'}
            className={`grid grid-cols-1 sm:grid-cols-3 gap-3 transition-all duration-300 ${hasChosenModel ? 'opacity-100' : 'animate-slide-down'}`}
        >
            {AVAILABLE_MODELS.map((model) => {
                const isSelected = transcribeProvider === model.provider && transcribeMode === model.mode;
                const cost = processVideoCostForSelection(model.provider as string, model.mode as string);

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
                        data-testid={`model-${model.mode}`}
                        onClick={(e) => {
                            e.stopPropagation();
                            setTranscribeProvider(model.provider as TranscribeProvider);
                            setTranscribeMode(model.mode as TranscribeMode);
                            setHasChosenModel(true);
                            setOverrideStep(2);
                            // Do NOT clear job here. We want to persist it until new upload or new start.
                            // onJobSelect(null);

                            // Wait for Step 1 to collapse (300ms) before scrolling to Step 2
                            setTimeout(scrollToUploadStep, 350);
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
                                    className={`w-5 h-5 rounded-full flex items-center justify-center ${model.mode === 'pro'
                                        ? 'bg-amber-400'
                                        : 'bg-emerald-500'
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

                        <div className="mb-4">
                            <span
                                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-wide backdrop-blur-md ${isSelected
                                    ? 'border-indigo-500/30 bg-indigo-500/10 text-indigo-200'
                                    : 'border-white/10 bg-white/5 text-white/70'
                                    }`}
                                aria-label={`${t('creditsCostLabel') || 'Cost'}: ${formatPoints(cost)}`}
                            >
                                <TokenIcon className="w-3.5 h-3.5" />
                                <span className="font-mono">{formatPoints(cost)}</span>
                            </span>
                        </div>

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
    ), [AVAILABLE_MODELS, transcribeProvider, transcribeMode, hasChosenModel, t, setTranscribeProvider, setTranscribeMode, setHasChosenModel, setOverrideStep, scrollToUploadStep]);

    const handleStepClick = useCallback(() => {
        if (currentStep === 1) {
            setLocalCollapsed(prev => !prev);
        } else {
            setOverrideStep(1);
            setLocalCollapsed(false);

            // Match scrolling behavior from ProcessView.tsx
            // Instead of scrolling to absolute top, scroll to the wrapper with correct offset
            const element = document.getElementById('step-1-wrapper');
            if (element) {
                const rect = element.getBoundingClientRect();
                const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                // 20px offset matches the one used in ProcessView.tsx for Step 1
                const offset = 20;
                const targetY = rect.top + scrollTop - offset;
                window.scrollTo({ top: targetY, behavior: 'smooth' });
            } else {
                // Fallback
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        }
    }, [currentStep, setOverrideStep]);

    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleStepClick();
        }
    }, [handleStepClick]);

    return useMemo(() => (
        <div id="model-selection-step" className="card space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div
                    role="button"
                    tabIndex={0}
                    onKeyDown={handleKeyDown}
                    className={`flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 1 ? 'opacity-100 hover:scale-[1.005]' : 'opacity-100 scale-[1.01]'}`}
                    onClick={handleStepClick}
                >
                    <span className={`flex items-center justify-center px-4 py-1.5 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 ${currentStep === 1
                        ? 'bg-[var(--accent)] border-[var(--accent)] text-white shadow-[0_0_20px_2px_var(--accent)] scale-105 ring-2 ring-[var(--accent)]/30'
                        : 'bg-[var(--surface-elevated)] border-[var(--accent)] text-[var(--accent)] shadow-[0_0_10px_-5px_var(--accent)]'
                        }`}>STEP 1</span>
                    <div>
                        <h3 className="text-xl font-semibold">{t('modelSelectTitle') || 'Pick a Model'}</h3>
                        {!hasChosenModel && (
                            <p className="text-sm text-[var(--muted)] mt-1 ml-0.5">{t('modelSelectSubtitle')}</p>
                        )}
                    </div>
                    {/* Chevron indicator for expand/collapse */}
                    <svg
                        className={`w-5 h-5 text-[var(--muted)] transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        data-testid="step-1-chevron"
                    >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                </div>
                <div className="flex items-center gap-3">
                    {/* Compact selected model indicator when collapsed */}
                    {!isExpanded && selectedModel && (
                        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)]">
                            <span className="text-sm">{selectedModel.icon(true)}</span>
                            <span className="text-sm font-medium text-[var(--foreground)]">{selectedModel.name}</span>
                        </div>
                    )}
                </div>
            </div>

            {/* Collapsible model grid with smooth animation */}
            <div className={`transition-all duration-300 ease-in-out overflow-hidden ${isExpanded ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0'}`}>
                {modelGrid}
            </div>
        </div>
    ), [t, currentStep, hasChosenModel, modelGrid, handleStepClick, handleKeyDown, isExpanded, selectedModel]);
}
