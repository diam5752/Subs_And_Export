import React, { useMemo, useCallback } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';

export function ModelSelector() {
    const { t } = useI18n();
    const {
        AVAILABLE_MODELS,
        transcribeProvider,
        transcribeMode,
        hasChosenModel,
        setTranscribeProvider,
        setTranscribeMode,
        setHasChosenModel,
        setOverrideStep,
        currentStep
    } = useProcessContext();

    // Local state to allow collapsing Step 1 even when it is active
    const [localCollapsed, setLocalCollapsed] = React.useState(false);

    // Reset local collapsed state when step changes
    React.useEffect(() => {
        if (currentStep !== 1) {
            setLocalCollapsed(false);
        }
    }, [currentStep]);

    // Collapsed state - expands automatically when on Step 1, unless manually collapsed
    const isExpanded = currentStep === 1 && !localCollapsed;

    // Derived: Find the currently selected model object for display when collapsed
    const selectedModel = useMemo(() => {
        return AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode);
    }, [AVAILABLE_MODELS, transcribeProvider, transcribeMode]);

    const scrollToUploadStep = useCallback(() => {
        setHasChosenModel(true);
        // Scroll to the next step's wrapper with offset
        setTimeout(() => {
            const element = document.getElementById('step-2-wrapper');
            if (element) {
                const rect = element.getBoundingClientRect();
                const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                // 20px offset matches the one used in ProcessView.tsx
                const offset = 20;
                const targetY = rect.top + scrollTop - offset;
                window.scrollTo({ top: targetY, behavior: 'smooth' });
            }
        }, 100);
    }, [setHasChosenModel]);

    const modelGrid = useMemo(() => (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
            {AVAILABLE_MODELS.map((model) => {
                const isSelected = transcribeProvider === model.provider && transcribeMode === model.mode;
                const isPro = model.id === 'pro';

                // Ensure consistent focus ring color (orange) for ALL cards
                const focusClass = "focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]";

                // Base container classes - subtle by default
                const containerClass = `relative w-full text-left p-4 rounded-xl border transition-all duration-200 outline-none ${focusClass} ${model.colorClass(isSelected)}`;

                // Background glow effect
                const bgClass = isPro ? 'bg-amber-500' : 'bg-emerald-500';

                return (
                    <button
                        key={model.id}
                        onClick={() => {
                            setTranscribeProvider(model.provider);
                            setTranscribeMode(model.mode);
                            setOverrideStep(2); // Move to next step immediately
                            scrollToUploadStep();
                        }}
                        className={containerClass}
                        role="radio"
                        aria-checked={isSelected}
                    >
                        <div className="flex items-start gap-4 relative z-10">
                            <div className="shrink-0 pt-1">
                                {model.icon(isSelected)}
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                    <h3 className={`font-semibold text-lg ${isSelected ? 'text-[var(--foreground)]' : 'text-[var(--foreground)]/80'}`}>
                                        {model.name}
                                    </h3>
                                    {model.badge && (
                                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider ${model.badgeColor}`}>
                                            {model.badge}
                                        </span>
                                    )}
                                </div>
                                <p className="text-sm text-[var(--muted)] leading-relaxed mb-4">
                                    {model.description}
                                </p>

                                {/* Stats - Visual Bars */}
                                <div className="space-y-2">
                                    {['speed', 'accuracy'].map((stat) => {
                                        const value = model.stats[stat as keyof typeof model.stats] as number;
                                        // 5 is max score
                                        const isFull = value >= 5;
                                        const isHalf = value >= 4 && value < 5;

                                        return (
                                            <div key={stat} className="flex items-center gap-3">
                                                <span className="text-[10px] font-bold text-[var(--muted)] uppercase tracking-wider w-16">
                                                    {t(stat === 'speed' ? 'modelStatSpeed' : 'modelStatAccuracy') || stat}
                                                </span>
                                                <div className="flex-1 h-1.5 bg-[var(--surface-elevated)] rounded-full overflow-hidden flex gap-0.5">
                                                    {[1, 2, 3, 4, 5].map((i) => (
                                                        <div
                                                            key={i}
                                                            className={`flex-1 rounded-full transition-all duration-500 ${i <= value ? (isPro ? 'bg-amber-400' : 'bg-emerald-400') : 'bg-transparent'}`}
                                                            style={{ opacity: i <= value ? 1 : 0.1 }}
                                                        />
                                                    ))}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>

                                {/* Karaoke Support Badge - Dynamic per model */}
                                <div className="mt-4 flex flex-wrap gap-2">
                                    {/* All models support karaoke now, but we highlight differences */}
                                    <div className={`text-[10px] font-bold px-2 py-1 rounded border flex items-center gap-1.5 ${isSelected
                                        ? (isPro ? 'bg-amber-500/10 border-amber-500/20 text-amber-200' : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-200')
                                        : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)]'
                                        }`}>
                                        <span className="text-xs">🎤</span>
                                        {t('karaokeSupported') || 'Karaoke Ready'}
                                    </div>

                                    {/* Additional feature badges based on model */}
                                    {isPro && (
                                        <div className={`text-[10px] font-bold px-2 py-1 rounded border flex items-center gap-1.5 ${isSelected
                                            ? 'bg-amber-500/10 border-amber-500/20 text-amber-200'
                                            : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)]'
                                            }`}>
                                            <span className="text-xs">🌍</span>
                                            {t('multilingualSupport') || '99+ Languages'}
                                        </div>
                                    )}
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
