import React, { useMemo, useCallback, memo } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { PhoneFrame } from '@/components/PhoneFrame';
import { PreviewPlayer } from '@/components/PreviewPlayer';
import { Sidebar } from './Sidebar';
import { VideoModal } from '@/components/VideoModal';
import { NewVideoConfirmModal } from './NewVideoConfirmModal';

const PreviewSectionLayout = memo(({
    resultsRef,
    currentStep,
    handleKeyDown,
    handleStepClick,
    selectedJob,
    isProcessing,
    t,
    transcribeProvider,
    displayedModel,
    processedCues,
    playerRef,
    videoUrl,
    playerSettings,
    handlePlayerTimeUpdate,
    handleExport,
    exportingResolutions,
    showPreview,
    setShowPreview,
    showNewVideoModal,
    setShowNewVideoModal,
    onNewVideoConfirm,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    activeSidebarTab
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
}: any) => {
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

                                                {/* Export Actions - Linear/Minimal Style */}
                                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-8 w-full max-w-[800px] mx-auto z-10 relative">
                                                    {/* SRT Button */}
                                                    <button
                                                        className="group relative h-[88px] rounded-lg bg-black/40 border border-white/10 hover:border-white/20 hover:bg-white/5 transition-all duration-200 overflow-hidden flex flex-col items-center justify-center gap-1"
                                                        onClick={() => handleExport('srt')}
                                                        disabled={exportingResolutions['srt']}
                                                    >
                                                        {exportingResolutions['srt'] ? (
                                                            <div className="flex flex-col items-center gap-2">
                                                                <span className="animate-spin text-white/40 text-xs">✦</span>
                                                                <span className="text-[10px] font-mono text-white/40 tracking-widest uppercase">Saving</span>
                                                            </div>
                                                        ) : (
                                                            <>
                                                                <div className="flex items-center gap-2 text-white/90 group-hover:text-white transition-colors">
                                                                    <svg className="w-4 h-4 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                                    </svg>
                                                                    <span className="text-lg font-medium tracking-tight">SRT</span>
                                                                </div>
                                                                <span className="text-[11px] text-white/40 font-medium">Subtitles Only</span>
                                                            </>
                                                        )}
                                                    </button>

                                                    {/* 1080p Button */}
                                                    <button
                                                        className="group relative h-[88px] rounded-lg bg-black/40 border border-white/10 hover:border-white/20 hover:bg-white/5 transition-all duration-200 overflow-hidden flex flex-col items-center justify-center gap-1"
                                                        onClick={() => handleExport('1080x1920')}
                                                        disabled={exportingResolutions['1080x1920']}
                                                    >
                                                        {exportingResolutions['1080x1920'] ? (
                                                            <div className="flex flex-col items-center gap-2">
                                                                <span className="animate-spin text-emerald-400 text-xs">✦</span>
                                                                <span className="text-[10px] font-mono text-white/40 tracking-widest uppercase">Rendering</span>
                                                            </div>
                                                        ) : (
                                                            <>
                                                                <span className="text-lg font-medium text-white/90 group-hover:text-white transition-colors tracking-tight">1080p</span>
                                                                <span className="text-[11px] text-white/40 font-medium">High Definition</span>
                                                            </>
                                                        )}
                                                    </button>

                                                    {/* 4K Button */}
                                                    <button
                                                        className="group relative h-[88px] rounded-lg bg-black/40 border border-white/10 hover:border-[var(--accent)]/30 hover:bg-[var(--accent)]/[0.03] transition-all duration-300 overflow-hidden flex flex-col items-center justify-center gap-1"
                                                        onClick={() => handleExport('2160x3840')}
                                                        disabled={exportingResolutions['2160x3840']}
                                                    >
                                                        {exportingResolutions['2160x3840'] ? (
                                                            <div className="flex flex-col items-center gap-2">
                                                                <span className="animate-spin text-[var(--accent)] text-xs">✦</span>
                                                                <span className="text-[10px] font-mono text-[var(--accent)] tracking-widest uppercase">Mastering</span>
                                                            </div>
                                                        ) : (
                                                            <>
                                                                <div className="flex items-center gap-1.5">
                                                                    {/* Gradient Text for 4K */}
                                                                    <span className="text-lg font-bold bg-gradient-to-br from-white via-white to-white/70 bg-clip-text text-transparent group-hover:from-[var(--accent)] group-hover:to-[var(--accent-secondary)] transition-all duration-300 tracking-tight">4K</span>
                                                                    <span className="px-1.5 py-0.5 rounded-[4px] bg-[var(--accent)]/10 border border-[var(--accent)]/20 text-[var(--accent)] text-[9px] font-bold uppercase tracking-wider">
                                                                        Ultra
                                                                    </span>
                                                                </div>
                                                                <span className="text-[11px] text-white/40 font-medium group-hover:text-[var(--accent)]/70 transition-colors">Cinema Grade</span>
                                                            </>
                                                        )}
                                                    </button>
                                                </div>

                                                {/* Process New Video Button */}
                                                <div className="mt-6 pt-6 border-t border-white/5 w-full max-w-[800px] mx-auto z-10 relative">
                                                    <button
                                                        onClick={() => setShowNewVideoModal(true)}
                                                        className="w-full group relative h-[56px] rounded-lg bg-transparent border border-dashed border-white/20 hover:border-[var(--accent)]/40 hover:bg-[var(--accent)]/5 transition-all duration-300 flex items-center justify-center gap-2"
                                                    >
                                                        <svg className="w-4 h-4 text-white/40 group-hover:text-[var(--accent)] transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                                                        </svg>
                                                        <span className="text-sm font-medium text-white/40 group-hover:text-[var(--accent)] transition-colors">
                                                            {t('newVideoButton') || 'Process New Video'}
                                                        </span>
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
                <NewVideoConfirmModal
                    isOpen={showNewVideoModal}
                    onClose={() => setShowNewVideoModal(false)}
                    onConfirm={onNewVideoConfirm}
                />
                <VideoModal
                    isOpen={showPreview}
                    onClose={() => setShowPreview(false)}
                    videoUrl={videoUrl || ''}
                />
            </div>
        </div>
    );
});

PreviewSectionLayout.displayName = 'PreviewSectionLayout';

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
        watermarkEnabled,
        setCurrentTime,
        playerRef,
        resultsRef,
        currentStep,
        setOverrideStep,
        AVAILABLE_MODELS,
        transcribeMode,
        handleExport,
        exportingResolutions,
        activeSidebarTab,
        onReset,
        setHasChosenModel,
        onJobSelect,
    } = useProcessContext();

    // Local state for VideoModal
    const [showPreview, setShowPreview] = React.useState(false);
    // Local state for NewVideoConfirmModal
    const [showNewVideoModal, setShowNewVideoModal] = React.useState(false);

    // Handler to start a new video workflow
    const handleNewVideoConfirm = useCallback(() => {
        onReset();
        setHasChosenModel(false);
        onJobSelect(null);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }, [onReset, setHasChosenModel, onJobSelect]);

    const playerSettings = useMemo(() => ({
        position: subtitlePosition,
        color: subtitleColor,
        fontSize: subtitleSize,
        karaoke: karaokeEnabled,
        maxLines: maxSubtitleLines,
        shadowStrength: shadowStrength,
        watermarkEnabled: watermarkEnabled
    }), [subtitlePosition, subtitleColor, subtitleSize, karaokeEnabled, maxSubtitleLines, shadowStrength, watermarkEnabled]);

    const handlePlayerTimeUpdate = useCallback((t: number) => {
        setCurrentTime(t);
    }, [setCurrentTime]);

    const handleStepClick = useCallback(() => {
        setOverrideStep(3);
        document.getElementById('preview-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, [setOverrideStep]);

    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleStepClick();
        }
    }, [handleStepClick]);

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
        <PreviewSectionLayout
            resultsRef={resultsRef}
            currentStep={currentStep}
            handleKeyDown={handleKeyDown}
            handleStepClick={handleStepClick}
            selectedJob={selectedJob}
            isProcessing={isProcessing}
            t={t}
            transcribeProvider={transcribeProvider}
            displayedModel={displayedModel}
            processedCues={processedCues}
            playerRef={playerRef}
            videoUrl={videoUrl}
            playerSettings={playerSettings}
            handlePlayerTimeUpdate={handlePlayerTimeUpdate}
            handleExport={handleExport}
            exportingResolutions={exportingResolutions}
            showPreview={showPreview}
            setShowPreview={setShowPreview}
            showNewVideoModal={showNewVideoModal}
            setShowNewVideoModal={setShowNewVideoModal}
            onNewVideoConfirm={handleNewVideoConfirm}
            activeSidebarTab={activeSidebarTab}
        />
    );
}