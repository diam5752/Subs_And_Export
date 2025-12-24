import React, { useMemo, useCallback, useState } from 'react';
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
    // Using render-time state derivation pattern to avoid useEffect warning
    const [prevCurrentStep, setPrevCurrentStep] = useState(currentStep);
    if (currentStep !== prevCurrentStep) {
        setPrevCurrentStep(currentStep);
        if (currentStep !== 1) {
            setLocalCollapsed(false);
        }
    }

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
            className={`grid grid-cols-1 sm:grid-cols-2 gap-4 p-1 transition-all duration-300 w-full ${hasChosenModel ? 'opacity-100' : 'animate-slide-down'}`}
        >
            {AVAILABLE_MODELS.map((model) => {
                const isSelected = transcribeProvider === model.provider && transcribeMode === model.mode;
                const cost = processVideoCostForSelection(model.provider as string, model.mode as string);
                const isPro = model.mode === 'pro';

                // Minimal Visual Stats
                // Standard: Speed 100%, Quality 75%
                // Pro: Speed 85%, Quality 100%

                // Theme Colors
                // Standard: Emerald (Green)
                // Pro: Neon Orange (Accent)
                const themeClass = isPro ? 'text-[var(--accent)]' : 'text-emerald-500';
                const bgClass = isPro ? 'bg-[var(--accent)]' : 'bg-emerald-500';
                const borderClass = isPro ? 'border-[var(--accent)]' : 'border-emerald-500';

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
                            setTimeout(scrollToUploadStep, 350);
                        }}
                        className={`p-6 rounded-2xl text-left transition-all duration-300 relative overflow-hidden group flex flex-col h-full backface-hidden will-change-transform transform-gpu focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)] focus-visible:ring-[var(--accent)] focus-visible:outline-none ${isSelected
                            ? 'glass-active scale-[1.02] z-10'
                            : `glass-premium hover:scale-[1.01] border-white/5 hover:${borderClass}/50 hover:bg-white/5`
                            } ${isPro && isSelected ? 'shadow-[0_0_30px_-5px_var(--accent)] border-[var(--accent)]' : ''} ${!isPro && isSelected ? 'shadow-[0_0_30px_-5px_rgba(16,185,129,0.4)] border-emerald-500' : ''} ${!isSelected ? (isPro ? 'hover:shadow-[0_10px_30px_-10px_rgba(249,115,22,0.15)]' : 'hover:shadow-[0_10px_30px_-10px_rgba(16,185,129,0.15)]') : ''}`}
                    >
                        {/* Header: Icon + Title */}
                        <div className="flex items-start justify-between mb-6 w-full">
                            <div className="flex flex-col gap-2">
                                <div className={`p-2.5 rounded-xl w-fit transition-colors duration-300 ${isSelected ? `${bgClass}/20 ${themeClass}` : `bg-white/5 ${isPro ? 'text-orange-500/50 group-hover:text-orange-400' : 'text-emerald-500/50 group-hover:text-emerald-400'}`}`}>
                                    {model.icon(isSelected)}
                                </div>
                                <div>
                                    <h3 className={`font-bold text-xl tracking-tight transition-colors duration-300 ${isSelected ? 'text-white' : 'text-[var(--foreground)]'}`}>
                                        {model.name}
                                    </h3>
                                    <p className="text-xs font-medium text-[var(--muted)] tracking-wide uppercase mt-0.5">
                                        {isPro ? t('modelProBadge') : t('modelStandardBadge')}
                                    </p>
                                </div>
                            </div>

                            {/* Cost Pill */}
                            <span
                                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold tracking-wide backdrop-blur-md transition-all duration-300 ${isSelected
                                    ? `${borderClass}/30 ${bgClass}/10 ${themeClass} shadow-[0_0_15px_-5px_currentColor]`
                                    : 'border-white/10 bg-white/5 text-[var(--muted)]'
                                    }`}
                            >
                                <TokenIcon className="w-3.5 h-3.5" />
                                <span>{formatPoints(cost)}</span>
                            </span>
                        </div>

                        {/* Minimal Stats: Speed & Quality (Out of 5) */}
                        <div className="space-y-4 mt-auto">
                            {/* Speed Bar - 5 futuristic segments */}
                            <div className="space-y-2">
                                <div className="flex justify-between text-[11px] font-bold uppercase tracking-wider text-[var(--muted)]">
                                    <span>{t('statSpeed')}</span>
                                </div>
                                <div className="flex gap-1.5">
                                    {[1, 2, 3, 4, 5].map((level) => {
                                        const speedLevel = isPro ? 4.5 : 5;
                                        const isFull = level <= Math.floor(speedLevel);
                                        const isHalf = level === Math.ceil(speedLevel) && speedLevel % 1 !== 0;
                                        const isEmpty = level > Math.ceil(speedLevel);

                                        return (
                                            <div
                                                key={level}
                                                className={`h-2.5 flex-1 rounded-full transition-all duration-500 relative overflow-hidden ${isEmpty
                                                    ? 'bg-white/[0.08] border border-white/[0.05]'
                                                    : ''} ${isFull
                                                        ? (isPro
                                                            ? 'bg-gradient-to-r from-orange-600 to-orange-400 shadow-[0_0_12px_rgba(249,115,22,0.4)]'
                                                            : 'bg-gradient-to-r from-emerald-600 to-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.4)]')
                                                        : ''}`}
                                                style={{ opacity: isSelected ? 1 : ((isFull || isHalf) ? 0.7 : 0.4) }}
                                            >
                                                {isHalf && (
                                                    <>
                                                        <div className={`absolute inset-0 w-1/2 rounded-l-full ${isPro ? 'bg-gradient-to-r from-orange-600 to-orange-500' : 'bg-gradient-to-r from-emerald-600 to-emerald-500'}`} />
                                                        <div className="absolute inset-0 w-full bg-white/[0.08] rounded-full" style={{ clipPath: 'inset(0 0 0 50%)' }} />
                                                    </>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* Accuracy Bar - 5 futuristic segments (Standard: 3.5/5) */}
                            <div className="space-y-2">
                                <div className="flex justify-between text-[11px] font-bold uppercase tracking-wider text-[var(--muted)]">
                                    <span>{t('statAccuracy')}</span>
                                </div>
                                <div className="flex gap-1.5">
                                    {[1, 2, 3, 4, 5].map((level) => {
                                        const qualityLevel = isPro ? 5 : 3.5;
                                        const isFull = level <= Math.floor(qualityLevel);
                                        const isHalf = level === Math.ceil(qualityLevel) && qualityLevel % 1 !== 0;
                                        const isEmpty = level > Math.ceil(qualityLevel);

                                        return (
                                            <div
                                                key={level}
                                                className={`h-2.5 flex-1 rounded-full transition-all duration-500 relative overflow-hidden ${isEmpty
                                                    ? 'bg-white/[0.08] border border-white/[0.05]'
                                                    : ''} ${isFull
                                                        ? (isPro
                                                            ? 'bg-gradient-to-r from-orange-600 to-orange-400 shadow-[0_0_12px_rgba(249,115,22,0.5)]'
                                                            : 'bg-gradient-to-r from-emerald-600 to-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.4)]')
                                                        : ''} ${isPro && level === 5 ? 'shadow-[0_0_20px_rgba(249,115,22,0.6)]' : ''}`}
                                                style={{ opacity: isSelected ? 1 : ((isFull || isHalf) ? 0.7 : 0.4) }}
                                            >
                                                {isHalf && (
                                                    <>
                                                        <div className={`absolute inset-0 w-1/2 rounded-l-full ${isPro ? 'bg-gradient-to-r from-orange-600 to-orange-500' : 'bg-gradient-to-r from-emerald-600 to-emerald-500'}`} />
                                                        <div className="absolute inset-0 w-full bg-white/[0.08] rounded-full" style={{ clipPath: 'inset(0 0 0 50%)' }} />
                                                    </>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        </div>

                        {/* Selection Indicator (Checkmark) */}
                        {isSelected && (
                            <div className={`absolute top-4 right-4 w-6 h-6 rounded-full flex items-center justify-center shadow-lg transform scale-100 opacity-100 transition-all duration-500 ${bgClass} text-white`}>
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                </svg>
                            </div>
                        )}
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
            <div className="flex flex-wrap items-center justify-between gap-3 relative z-50">
                <div
                    role="button"
                    tabIndex={0}
                    onKeyDown={handleKeyDown}
                    className={`flex items-center gap-3 transition-all duration-300 cursor-pointer group/step ${currentStep !== 1 ? 'opacity-100 hover:scale-[1.005]' : 'opacity-100 scale-[1.01]'}`}
                    onClick={handleStepClick}
                >
                    <span className={`flex items-center justify-center px-4 py-1 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 shrink-0 ${currentStep === 1
                        ? 'bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] border-transparent text-white shadow-[0_0_20px_var(--accent)] scale-105'
                        : 'glass-premium border-[var(--border)] text-[var(--muted)]'
                        }`}>STEP 1</span>

                    <div className="min-w-0">
                        <h3 className="text-xl font-semibold truncate">{t('modelSelectTitle') || 'Pick a Model'}</h3>
                        {!hasChosenModel && (
                            <p className="text-sm text-[var(--muted)] mt-0.5 ml-0.5 truncate">{t('modelSelectSubtitle')}</p>
                        )}
                    </div>

                    <div
                        className="group/info relative z-[100] shrink-0 rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                        role="button"
                        tabIndex={0}
                        aria-label={t('modelInfo') || "Model comparison information"}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                e.stopPropagation();
                            }
                        }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <svg className="w-5 h-5 text-white/50 group-focus/info:text-white group-hover/info:text-white cursor-help transition-all duration-200" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>

                        {/* Tooltip Content - Confirmed Solid Background */}
                        <div className="absolute right-0 top-full mt-3 w-80 bg-zinc-950 border border-neutral-800 rounded-xl p-5 shadow-[0_20px_60px_rgba(0,0,0,0.8)] opacity-0 invisible group-hover/info:opacity-100 group-hover/info:visible group-focus/info:opacity-100 group-focus/info:visible transition-all duration-150 z-[1002] origin-top-right">
                            <div className="space-y-5">
                                <div className="space-y-2 text-left">
                                    <div className="flex items-center gap-2 text-emerald-500 font-bold text-xs uppercase tracking-wider">
                                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                                        Quick & Simple
                                    </div>
                                    <p className="text-[13px] leading-relaxed text-zinc-400">
                                        <strong className="text-zinc-200">Great for basic content.</strong> Works well with clear audio and simple speech. Budget-friendly for everyday videos.
                                    </p>
                                </div>
                                <div className="space-y-2 border-t border-white/5 pt-4 text-left">
                                    <div className="flex items-center gap-2 text-orange-500 font-bold text-xs uppercase tracking-wider">
                                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" /></svg>
                                        Creator&apos;s Choice ✨
                                    </div>
                                    <p className="text-[13px] leading-relaxed text-zinc-400">
                                        <strong className="text-white">What top creators use.</strong> Handles accents, background noise, music &amp; multiple languages flawlessly. Worth every credit.
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Chevron indicator for expand/collapse */}
                    <svg
                        className={`w-5 h-5 text-[var(--muted)] transition-transform duration-300 shrink-0 ${isExpanded ? 'rotate-180' : ''}`}
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
