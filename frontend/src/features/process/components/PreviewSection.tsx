import React, { useMemo, useCallback } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { PhoneFrame } from '@/components/PhoneFrame';
import { PreviewPlayer } from '@/components/PreviewPlayer';
import { Sidebar } from './Sidebar';
import { VideoModal } from '@/components/VideoModal';
import { TokenIcon } from '@/components/icons';

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
                                                <div className="flex flex-col sm:flex-row gap-5 mt-8 w-full max-w-[600px] mx-auto z-10 relative">
                                                    {/* Full HD Button - Blended Clean */}
                                                    <button
                                                        className="group relative flex-1 h-[88px] rounded-xl bg-white/[0.02] border border-white/10 hover:bg-white/[0.04] hover:border-white/20 transition-all duration-500 overflow-hidden"
                                                        onClick={() => handleExport('1080x1920')}
                                                        disabled={exportingResolutions['1080x1920']}
                                                    >
                                                        {exportingResolutions['1080x1920'] ? (
                                                            <div className="relative z-10 h-full flex items-center justify-center gap-3">
                                                                <span className="animate-spin text-white/50">✦</span>
                                                                <span className="font-mono text-xs text-white/50 tracking-widest uppercase">Processing</span>
                                                            </div>
                                                        ) : (
                                                            <div className="relative z-10 h-full px-5 flex items-center justify-between">
                                                                <span className="text-[15px] font-medium text-white tracking-wide group-hover:text-white transition-colors">Export 1080p</span>
                                                                <div className="w-8 h-8 flex items-center justify-center rounded-full bg-white/5 border border-white/5 group-hover:bg-white text-white/40 group-hover:text-black transition-all duration-500">
                                                                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                                                    </svg>
                                                                </div>
                                                            </div>
                                                        )}
                                                    </button>

                                                    {/* 4K Button - Luminous Void Clean */}
                                                    <button
                                                        className="group relative flex-1 h-[88px] rounded-xl bg-white/[0.02] border border-white/10 hover:border-[var(--accent)] hover:bg-white/[0.05] transition-all duration-500 overflow-hidden"
                                                        onClick={() => handleExport('2160x3840')}
                                                        disabled={exportingResolutions['2160x3840']}
                                                    >
                                                        {/* Luminous background gradient */}
                                                        <div className="absolute inset-0 bg-gradient-to-br from-[var(--accent)]/10 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-700" />

                                                        {exportingResolutions['2160x3840'] ? (
                                                            <div className="relative z-10 h-full flex items-center justify-center gap-3">
                                                                <span className="animate-spin text-[var(--accent)]">✦</span>
                                                                <span className="font-mono text-xs text-white/50 tracking-widest uppercase">Mastering</span>
                                                            </div>
                                                        ) : (
                                                            <div className="relative z-10 h-full px-5 flex items-center justify-between">
                                                                <span className="text-[15px] font-medium text-white tracking-wide group-hover:text-white transition-colors">Export 4K</span>

                                                                {/* Download Icon (matching 1080p style but with accent hover) */}
                                                                <div className="w-8 h-8 flex items-center justify-center rounded-full bg-white/5 border border-white/5 group-hover:bg-[var(--accent)] text-white/40 group-hover:text-white group-hover:shadow-[0_0_15px_var(--accent)] transition-all duration-500">
                                                                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                                                    </svg>
                                                                </div>
                                                            </div>
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
