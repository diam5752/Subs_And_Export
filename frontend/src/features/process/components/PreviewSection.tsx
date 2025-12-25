import React, { useMemo, useCallback, memo } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { usePlaybackContext } from '../PlaybackContext';
import { PhoneFrame } from '@/components/PhoneFrame';
import { PreviewPlayer } from '@/components/PreviewPlayer';
import { Sidebar } from './Sidebar';
import { VideoModal } from '@/components/VideoModal';
import { NewVideoConfirmModal } from './NewVideoConfirmModal';
import { Spinner } from '@/components/Spinner';

const resolveTierFromJob = (provider?: string | null, model?: string | null): 'standard' | 'pro' => {
    const normalizedProvider = (provider ?? '').trim().toLowerCase();
    const normalizedModel = (model ?? '').trim().toLowerCase();
    if (normalizedModel === 'pro' || normalizedModel === 'standard') return normalizedModel as 'standard' | 'pro';
    if (normalizedModel.includes('turbo') || normalizedModel.includes('enhanced')) return 'standard';
    if (normalizedModel.includes('large')) return 'pro';
    if (normalizedProvider === 'openai' || normalizedModel.includes('ultimate') || normalizedModel.includes('whisper-1')) return 'pro';
    return 'standard';
};

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
    activeSidebarTab,
    isExpanded // New prop, received from parent
// eslint-disable-next-line @typescript-eslint/no-explicit-any
}: any) => {
    return (
        <div id="preview-section" className={`card space-y-4 transition-all duration-500 ${!selectedJob && !isProcessing ? 'opacity-50 grayscale' : ''}`} ref={resultsRef}>

            <div
                role="button"
                tabIndex={0}
                aria-expanded={isExpanded}
                onKeyDown={handleKeyDown}
                className={`mb-2 flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 3 ? (selectedJob?.status === 'completed' ? 'opacity-100 hover:scale-[1.005]' : 'opacity-40 grayscale blur-[1px]') : 'opacity-100 scale-[1.01]'}`}
                onClick={handleStepClick}
            >
                <span className={`flex items-center justify-center px-4 py-1 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 ${currentStep === 3
                    ? 'bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] border-transparent text-white shadow-[0_0_20px_var(--accent)] scale-105'
                    : 'glass-premium border-[var(--border)] text-[var(--muted)]'
                    }`}>STEP 3</span>
                <h3 className="text-xl font-semibold">{t('previewWindowLabel') || 'Preview & Export'}</h3>
                {/* Chevron indicator for expand/collapse */}
                <svg
                    className={`w-5 h-5 text-[var(--muted)] transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    data-testid="step-3-chevron"
                >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
            </div>

            {/* Collapsible content with smooth animation */}
            <div className={`transition-all duration-300 ease-in-out overflow-hidden ${isExpanded ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0'}`} >

                <div className="space-y-4 min-h-[200px]">
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
                                        {t('subtitlesReady') || 'Live Preview'}
                                    </h3>
                                    <p className="text-sm text-[var(--muted)]">{t('liveOutputSubtitle')}</p>
                                </div>
                                <div className="flex items-center justify-end">
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
                                                            {videoUrl ? (
                                                                <PreviewPlayer
                                                                    ref={playerRef}
                                                                    videoUrl={videoUrl}
                                                                    cues={processedCues || []}
                                                                    settings={playerSettings}
                                                                    onTimeUpdate={handlePlayerTimeUpdate}
                                                                    initialTime={processedCues && processedCues.length > 0 ? processedCues[0].start : 0}
                                                                />
                                                            ) : (
                                                                <div className="relative group w-full h-full flex items-center justify-center bg-gray-900">
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
                                                            aria-busy={exportingResolutions['srt']}
                                                            data-testid="srt-btn"
                                                        >
                                                            {exportingResolutions['srt'] ? (
                                                                <div className="flex flex-col items-center gap-2">
                                                                    <Spinner className="w-4 h-4 text-white/40" />
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
                                                            aria-busy={exportingResolutions['1080x1920']}
                                                            data-testid="download-1080p-btn"
                                                        >
                                                            {exportingResolutions['1080x1920'] ? (
                                                                <div className="flex flex-col items-center gap-2">
                                                                    <Spinner className="w-4 h-4 text-emerald-400" />
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
                                                            aria-busy={exportingResolutions['2160x3840']}
                                                        >
                                                            {exportingResolutions['2160x3840'] ? (
                                                                <div className="flex flex-col items-center gap-2">
                                                                    <Spinner className="w-4 h-4 text-[var(--accent)]" />
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
    const { setCurrentTime } = usePlaybackContext();

    // Local state for NewVideoConfirmModal
    const [showNewVideoModal, setShowNewVideoModal] = React.useState(false);

    // Local state to allow collapsing Step 3 even when it is active
    const [localCollapsed, setLocalCollapsed] = React.useState(false);

    // Reset local collapsed state when step changes
    React.useEffect(() => {
        if (currentStep !== 3) {
            setLocalCollapsed(false);
        }
    }, [currentStep]);

    // Collapsed state - expands automatically when on Step 3, unless manually collapsed
    const isExpanded = currentStep === 3 && !localCollapsed;

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
        if (currentStep === 3) {
            setLocalCollapsed(prev => !prev);
        } else {
            setOverrideStep(3);
            setLocalCollapsed(false);
            // Wait for any panel transitions (Model selector or Upload section) to finish
            setTimeout(() => {
                document.getElementById('step-3-wrapper')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 350);
        }
    }, [currentStep, setOverrideStep]);

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

            const jobTier = resolveTierFromJob(provider, model);
            return AVAILABLE_MODELS.find(m => m.mode === jobTier);
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
            isExpanded={isExpanded}
        />
    );
}
