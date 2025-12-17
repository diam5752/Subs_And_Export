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
        progress,
        statusMessage,
        onCancelProcessing,
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
        document.getElementById('preview-section')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleStepClick();
        }
    };

    const selectedModel = useMemo(() =>
        AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode),
        [AVAILABLE_MODELS, transcribeProvider, transcribeMode]);

    return (
        <div id="preview-section" className={`space-y-4 scroll-mt-[100px] transition-all duration-500 ${!selectedJob && !isProcessing ? 'opacity-50 grayscale' : ''}`} ref={resultsRef}>

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
                {(!(isProcessing || (selectedJob && selectedJob.status !== 'pending'))) ? (
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
                                    {(isProcessing ? t('statusProcessingEllipsis') : 'Live Preview')}
                                </h3>
                                <p className="text-sm text-[var(--muted)]">{t('liveOutputSubtitle')}</p>
                            </div>
                        </div>

                        {isProcessing && (
                            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 space-y-3 animate-fade-in">
                                <div className="flex items-center justify-between text-sm">
                                    <span className="font-medium">{statusMessage || t('progressLabel')}</span>
                                    <span className="text-[var(--accent)] font-semibold">{progress}%</span>
                                </div>
                                <div className="w-full bg-[var(--surface)] rounded-full h-2 overflow-hidden">
                                    <div
                                        className="progress-bar bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] h-2 rounded-full"
                                        style={{ width: `${progress}% ` }}
                                    />
                                </div>
                                {onCancelProcessing && (
                                    <div className="flex justify-end pt-1">
                                        <button
                                            onClick={onCancelProcessing}
                                            className="px-4 py-1.5 rounded-lg text-sm font-medium bg-[var(--danger)]/10 text-[var(--danger)] hover:bg-[var(--danger)]/20 border border-[var(--danger)]/30 transition-colors"
                                        >
                                            {t('cancelProcessing')}
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

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
                                                        {selectedModel && (
                                                            <span className="text-sm">{selectedModel.icon(true)}</span>
                                                        )}
                                                        <span className="text-xs font-medium text-white/80">
                                                            {(() => {
                                                                const provider = selectedJob?.result_data?.transcribe_provider || transcribeProvider;
                                                                if (provider === 'local') return 'Standard';
                                                                if (provider === 'groq') return 'Enhanced';
                                                                if (provider === 'openai') return 'Ultimate';
                                                                return provider;
                                                            })()}
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
                                                <div className="flex flex-col sm:flex-row gap-4 mt-8 w-full max-w-[500px] mx-auto z-10 relative">
                                                    {/* Full HD Button */}
                                                    <button
                                                        className="flex-1 py-3 px-6 rounded-xl flex items-center justify-center gap-2 bg-[var(--surface-elevated)] border border-[var(--border)] hover:bg-[var(--surface)] hover:border-[var(--accent)]/50 transition-all transform hover:-translate-y-0.5 shadow-lg"
                                                        onClick={() => handleExport('1080x1920')}
                                                        disabled={exportingResolutions['1080x1920']}
                                                    >
                                                        {exportingResolutions['1080x1920'] ? (
                                                            <><span className="animate-spin">⏳</span> Rendering HD...</>
                                                        ) : (
                                                            <>
                                                                <span className="text-xl">📺</span>
                                                                <div className="flex flex-col items-start leading-tight">
                                                                    <span className="font-bold">Export Full HD</span>
                                                                    <span className="text-[10px] opacity-60">1080p • Standard</span>
                                                                </div>
                                                            </>
                                                        )}
                                                    </button>

                                                    {/* 4K Button (VIP/Turbo style - Cyan/Blue) */}
                                                    <button
                                                        className="flex-1 py-3 px-6 rounded-xl flex items-center justify-center gap-2 shadow-lg shadow-cyan-500/20 hover:shadow-cyan-500/40 transition-all transform hover:-translate-y-0.5 bg-gradient-to-r from-cyan-500 to-blue-600 text-white border border-cyan-400/30"
                                                        onClick={() => handleExport('2160x3840')}
                                                        disabled={exportingResolutions['2160x3840']}
                                                    >
                                                        {exportingResolutions['2160x3840'] ? (
                                                            <><span className="animate-spin">⏳</span> Rendering 4K...</>
                                                        ) : (
                                                            <>
                                                                <span className="text-xl">🚀</span>
                                                                <div className="flex flex-col items-start leading-tight">
                                                                    <span className="font-bold">Export 4K Turbo</span>
                                                                    <span className="text-[10px] opacity-90 font-medium">2160p • VIP Quality</span>
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
