import React, { useMemo, useCallback } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { PhoneFrame } from '@/components/PhoneFrame';
import { PreviewPlayer } from '@/components/PreviewPlayer';
import { Sidebar } from './Sidebar';
import { VideoModal } from '@/components/VideoModal';

export function PreviewSection() {
    const { t } = useI18n();
    const {
        selectedJob,
        isProcessing,
        transcribeProvider,
        videoUrl,
        processedCues,
        subtitlePosition,
        subtitleColor,
        subtitleSize,
        karaokeEnabled,
        maxSubtitleLines,
        shadowStrength,
        setCurrentTime,
        playerRef,
        resultsRef,
        currentStep,
        setOverrideStep,
        AVAILABLE_MODELS,
        transcribeMode,
        handleExport,
        exportingResolutions,
    } = useProcessContext();

    // Local state for VideoModal
    const [showPreview, setShowPreview] = React.useState(false);

    const playerSettings = useMemo(() => ({
        position: subtitlePosition,
        color: subtitleColor,
        fontSize: subtitleSize,
        karaoke: karaokeEnabled,
        maxLines: maxSubtitleLines,
        shadowStrength: shadowStrength
    }), [subtitlePosition, subtitleColor, subtitleSize, karaokeEnabled, maxSubtitleLines, shadowStrength]);

    const handlePlayerTimeUpdate = useCallback((t: number) => {
        setCurrentTime(t);
    }, [setCurrentTime]);

    const handleStepClick = () => {
        setOverrideStep(3);
        document.getElementById('preview-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleStepClick();
        }
    };

    const displayedModel = useMemo(() => {
        // If a job is completed, we MUST show the model that generated it, NOT the current selection
        if (selectedJob?.status === 'completed' && selectedJob.result_data) {
            const provider = selectedJob.result_data.transcribe_provider;
            const model = selectedJob.result_data.model_size;

            // Map job data back to AVAILABLE_MODELS entry
            return AVAILABLE_MODELS.find(m => {
                if (m.provider !== provider) return false;

                // Specific matching logic strictly for Groq vs others
                if (provider === 'groq') {
                    const isEnhancedJob = model === 'enhanced' || (model && model.includes('turbo'));
                    const isUltimateJob = model === 'ultimate' || (model && !model.includes('turbo') && !model.includes('enhanced'));

                    if (m.mode === 'enhanced') return isEnhancedJob;
                    if (m.mode === 'ultimate') return isUltimateJob;
                    return false;
                }

                // For others (whispercpp, etc)
                // Since we only have one model per provider for non-Groq currently (Standard = whispercpp),
                // we should match purely on provider to persist the tag regardless of current UI selection.
                return true;
            });
        }

        // Default to current selection
        return AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode);
    }, [AVAILABLE_MODELS, selectedJob, transcribeProvider, transcribeMode]);

    return (
        <div id="preview-section" className={`space-y-4 scroll-mt-32 transition-all duration-500 ${!selectedJob && !isProcessing ? 'opacity-50 grayscale' : ''}`} ref={resultsRef}>

            <div
                role="button"
                tabIndex={0}
                onKeyDown={handleKeyDown}
                className={`mb-2 flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 3 ? 'opacity-40 grayscale blur-[1px] hover:opacity-80 hover:grayscale-0 hover:blur-0' : 'opacity-100 scale-[1.01]'}`}
                onClick={handleStepClick}
            >
                <span className={`flex items-center justify-center px-4 py-1.5 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 ${currentStep === 3
                    ? 'bg-[var(--accent)] border-[var(--accent)] text-white shadow-[0_0_20px_2px_var(--accent)] scale-105 ring-2 ring-[var(--accent)]/30'
                    : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)] group-hover/step:border-[var(--accent)]/50 group-hover/step:text-[var(--accent)]'
                    }`}>STEP 3</span>
                <h3 className="text-xl font-semibold">Preview & Export</h3>
            </div>

            <div className="card space-y-4 min-h-[200px]">
                {(!selectedJob || selectedJob.status !== 'completed') ? (
                    <div className="py-20 flex flex-col items-center justify-center text-center text-[var(--muted)] border-2 border-dashed border-[var(--border)]/50 rounded-xl bg-[var(--surface-elevated)]/30">
                        <div className="text-5xl mb-4 opacity-20">🎬</div>
                        <p className="font-semibold text-lg opacity-60">Result Preview</p>
                        <p className="text-sm mt-1 opacity-40 max-w-[200px]">Generate a video to see the preview and export options here</p>
                    </div>
                ) : (
                    <>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                                <h3 className="text-2xl font-semibold break-words [overflow-wrap:anywhere]">
                                    Live Preview
                                </h3>
                                <p className="text-sm text-[var(--muted)]">{t('liveOutputSubtitle')}</p>
                            </div>
                            <div className="flex items-center justify-end">
                                <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-300">
                                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                                    {t('subtitlesReady')}
                                </span>
                            </div>
                        </div>

                        {!isProcessing && selectedJob && selectedJob.status === 'completed' ? (
                            <div className="animate-fade-in relative">
                                <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-r from-[var(--accent)] via-[var(--accent-secondary)] to-[var(--accent)] bg-[length:200%_100%] animate-shimmer opacity-80" />
                                <div className="preview-card-glow absolute inset-0 rounded-2xl" />

                                <div className="relative rounded-2xl border border-white/10 bg-[var(--surface-elevated)] overflow-hidden">
                                    <div className="flex flex-col lg:flex-row gap-6 transition-all duration-500 ease-in-out lg:h-[850px]">
                                        {/* Preview Player Area */}
                                        <div className="flex-1 flex flex-col items-center min-w-0">
                                            <div className="w-full h-full bg-black/20 rounded-2xl border border-white/5 flex flex-col items-center justify-center p-4 lg:p-8 relative overflow-hidden backdrop-blur-sm transition-all duration-500">
                                                {(selectedJob?.result_data?.transcribe_provider || transcribeProvider) && (
                                                    <div className="absolute top-4 left-4 z-10 flex items-center gap-2 px-3 py-1.5 rounded-full bg-black/60 border border-white/10 backdrop-blur-md">
                                                        {displayedModel && (
                                                            <span className="text-sm">{displayedModel.icon(true)}</span>
                                                        )}
                                                        <span className="text-xs font-medium text-white/80">
                                                            {displayedModel?.name || 'Standard'}
                                                        </span>
                                                    </div>
                                                )}

                                                <div className="relative h-[min(70dvh,600px)] w-auto aspect-[9/16] max-w-full shadow-2xl transition-all duration-500 hover:scale-[1.01] lg:h-[85%] lg:max-h-[600px] flex-shrink-0">
                                                    <PhoneFrame className="w-full h-full" showSocialOverlays={false}>
                                                        {processedCues && processedCues.length > 0 ? (
                                                            <PreviewPlayer
                                                                ref={playerRef}
                                                                videoUrl={videoUrl || ''}
                                                                cues={processedCues}
                                                                settings={playerSettings}
                                                                onTimeUpdate={handlePlayerTimeUpdate}
                                                                initialTime={processedCues && processedCues.length > 0 ? processedCues[0].start : 0}
                                                            />
                                                        ) : (
                                                            <div className="relative group w-full h-full flex items-center justify-center bg-gray-900">
                                                                {videoUrl && (
                                                                    <video
                                                                        src={`${videoUrl}#t=0.5`}
                                                                        className="absolute inset-0 w-full h-full object-cover opacity-30 blur-sm"
                                                                        muted
                                                                        playsInline
                                                                    />
                                                                )}
                                                                <div className="relative z-10 text-center p-6">
                                                                    <div className="mb-3 text-4xl animate-bounce">👆</div>
                                                                    <p className="text-sm font-medium text-white/90">{t('clickToPreview') || 'Preview Pending...'}</p>
                                                                </div>
                                                            </div>
                                                        )}
                                                    </PhoneFrame>
                                                </div>

                                                {/* Export Actions */}
                                                <div className="flex flex-col sm:flex-row gap-5 mt-8 w-full max-w-[560px] mx-auto z-10 relative">
                                                    {/* Full HD Button - "Refined Glass" (Apple) */}
                                                    <button
                                                        className="group relative flex-1 py-4 px-6 rounded-2xl flex items-center justify-center gap-4 bg-white/5 backdrop-blur-xl border border-white/10 hover:bg-white/10 hover:border-white/20 transition-all duration-300 active:scale-[0.98] shadow-sm hover:shadow-lg hover:shadow-black/20 overflow-hidden"
                                                        onClick={() => handleExport('1080x1920')}
                                                        disabled={exportingResolutions['1080x1920']}
                                                    >
                                                        {exportingResolutions['1080x1920'] ? (
                                                            <><span className="animate-spin text-lg opacity-70">⏳</span> <span className="text-sm font-medium text-white/70">Processing...</span></>
                                                        ) : (
                                                            <>
                                                                <div className="flex items-center justify-center w-10 h-10 rounded-full bg-white/5 group-hover:bg-white/10 transition-colors text-white/80 group-hover:text-white">
                                                                    {/* HD Icon: Video Camera */}
                                                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.818v6.364a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                                                    </svg>
                                                                </div>
                                                                <div className="flex flex-col items-start gap-0.5">
                                                                    <span className="font-semibold text-[15px] text-white/90 group-hover:text-white tracking-wide">Export Full HD</span>
                                                                    <span className="text-[11px] font-medium text-white/40 group-hover:text-white/60">1080p • Standard</span>
                                                                </div>
                                                            </>
                                                        )}
                                                    </button>

                                                    {/* 4K Button - "Deep Dimensions" (Google/Material 3) */}
                                                    <button
                                                        className="group relative flex-1 py-4 px-6 rounded-2xl flex items-center justify-center gap-4 bg-gradient-to-br from-[#1A1A2E] via-[#16213E] to-[#0F3460] border border-white/10 hover:border-white/20 transition-all duration-500 hover:scale-[1.02] active:scale-[0.98] shadow-lg hover:shadow-indigo-500/20 overflow-hidden"
                                                        onClick={() => handleExport('2160x3840')}
                                                        disabled={exportingResolutions['2160x3840']}
                                                    >
                                                        {/* Subtle Aurora Glow background */}
                                                        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-purple-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-700 blur-xl" />

                                                        {/* Sharp "Holographic" Shine */}
                                                        <div className="absolute inset-0 -translate-x-[150%] group-hover:translate-x-[150%] transition-transform duration-1000 bg-gradient-to-r from-transparent via-white/10 to-transparent -skew-x-12 ease-[cubic-bezier(0.4,0,0.2,1)]" />

                                                        {exportingResolutions['2160x3840'] ? (
                                                            <><span className="animate-spin text-lg">⏳</span> <span className="text-sm font-medium text-white">Mastering 4K...</span></>
                                                        ) : (
                                                            <>
                                                                <div className="relative flex items-center justify-center w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-indigo-400/30 text-indigo-300 group-hover:text-white group-hover:border-indigo-400/50 transition-colors shadow-inner">
                                                                    {/* 4K Icon: Sparkles/Stars */}
                                                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                                                                    </svg>
                                                                </div>
                                                                <div className="flex flex-col items-start gap-0.5 relative z-10">
                                                                    <span className="font-semibold text-[15px] text-white tracking-wide drop-shadow-sm">Export 4K</span>
                                                                    <div className="flex items-center gap-1.5">
                                                                        <span className="text-[11px] font-bold text-transparent bg-clip-text bg-gradient-to-r from-indigo-300 to-purple-300 uppercase tracking-wider">Pro Quality</span>
                                                                    </div>
                                                                </div>
                                                            </>
                                                        )}
                                                    </button>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Sidebar Controls */}
                                        <Sidebar />
                                    </div>
                                </div>
                            </div>
                        ) : null}
                    </>
                )}
                <VideoModal
                    isOpen={showPreview}
                    onClose={() => setShowPreview(false)}
                    videoUrl={videoUrl || ''}
                />
            </div>
        </div>
    );
}
