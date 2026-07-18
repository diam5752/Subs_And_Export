import React, { memo, useCallback, useMemo } from 'react';
import { PhoneFrame } from '@/components/PhoneFrame';
import { PreviewPlayer, type PreviewPlayerHandle } from '@/components/PreviewPlayer';
import { Spinner } from '@/components/Spinner';
import { useI18n } from '@/context/I18nContext';
import type { MessageKey } from '@/context/i18nMessages';
import type { JobResponse } from '@/lib/api';
import { resolveTranscriptionTier } from '@/lib/transcription';
import { usePlaybackContext } from '../PlaybackContext';
import { useProcessContext } from '../ProcessContext';
import { NewVideoConfirmModal } from './NewVideoConfirmModal';
import { Sidebar } from './Sidebar';

type PreviewSectionLayoutProps = {
    resultsRef: React.RefObject<HTMLDivElement | null>;
    currentStep: number;
    handleStepClick: () => void;
    selectedJob: JobResponse | null;
    isProcessing: boolean;
    t: (key: MessageKey, params?: Record<string, string | number>) => string;
    transcribeProvider: string | null;
    displayedModel?: {
        icon: (selected: boolean) => React.ReactNode;
        name: string;
    };
    processedCues: React.ComponentProps<typeof PreviewPlayer>['cues'];
    playerRef: React.RefObject<PreviewPlayerHandle | null>;
    videoUrl: string | null;
    playerSettings: React.ComponentProps<typeof PreviewPlayer>['settings'];
    handlePlayerTimeUpdate: (time: number) => void;
    handleExport: (resolution: string) => Promise<void>;
    exportingResolutions: Record<string, boolean>;
    exportError: string | null;
    showNewVideoModal: boolean;
    setShowNewVideoModal: React.Dispatch<React.SetStateAction<boolean>>;
    onNewVideoConfirm: () => void;
    isExpanded: boolean;
};

type ExportOption = {
    resolution: '1080x1920' | 'srt' | 'vtt' | 'txt' | '2160x3840';
    label: string;
    descriptionKey: MessageKey;
    loadingKey: MessageKey;
    testId: string;
    primary?: boolean;
};

const EXPORT_OPTIONS: ExportOption[] = [
    {
        resolution: '1080x1920',
        label: '1080p',
        descriptionKey: 'exportHdDesc',
        loadingKey: 'exportRendering',
        testId: 'download-1080p-btn',
        primary: true,
    },
    {
        resolution: 'srt',
        label: 'SRT',
        descriptionKey: 'subtitleFileSrtDesc',
        loadingKey: 'exportSaving',
        testId: 'srt-btn',
    },
    {
        resolution: 'vtt',
        label: 'VTT',
        descriptionKey: 'subtitleFileVttDesc',
        loadingKey: 'exportSaving',
        testId: 'vtt-btn',
    },
    {
        resolution: 'txt',
        label: 'TXT',
        descriptionKey: 'subtitleFileTxtDesc',
        loadingKey: 'exportSaving',
        testId: 'txt-btn',
    },
    {
        resolution: '2160x3840',
        label: '4K',
        descriptionKey: 'export4kDesc',
        loadingKey: 'exportMastering',
        testId: 'download-4k-btn',
    },
];

const ExportAction = memo(({
    option,
    isExporting,
    onExport,
    t,
}: {
    option: ExportOption;
    isExporting: boolean;
    onExport: (resolution: string) => Promise<void>;
    t: PreviewSectionLayoutProps['t'];
}) => (
    <button
        type="button"
        className={`editor-export-action ${option.primary ? 'editor-export-action-primary' : ''}`}
        onClick={() => onExport(option.resolution)}
        disabled={isExporting}
        aria-busy={isExporting}
        data-testid={option.testId}
    >
        {isExporting ? (
            <span className="editor-export-loading">
                <Spinner className="h-4 w-4" />
                <span>{t(option.loadingKey)}</span>
            </span>
        ) : (
            <>
                <span className="editor-export-label">{option.label}</span>
                <span className="editor-export-description">{t(option.descriptionKey)}</span>
            </>
        )}
    </button>
));
ExportAction.displayName = 'ExportAction';

const PreviewSectionLayout = memo(({
    resultsRef,
    currentStep,
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
    exportError,
    showNewVideoModal,
    setShowNewVideoModal,
    onNewVideoConfirm,
    isExpanded,
}: PreviewSectionLayoutProps) => (
    <div
        id="preview-section"
        className={`card editor-section ${!selectedJob && !isProcessing ? 'opacity-50 grayscale' : ''}`}
        ref={resultsRef}
    >
        <button
            type="button"
            className={`editor-step-toggle ${currentStep !== 3 && selectedJob?.status !== 'completed' ? 'opacity-40 grayscale' : ''}`}
            onClick={handleStepClick}
            aria-expanded={isExpanded}
            aria-controls="editor-section-content"
        >
            <span className={`editor-step-badge ${currentStep === 3 ? 'editor-step-badge-active' : ''}`}>
                {t('step3Label')}
            </span>
            <span className="editor-step-title">{t('previewWindowLabel')}</span>
            <svg
                className={`editor-step-chevron ${isExpanded ? 'rotate-180' : ''}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                data-testid="step-3-chevron"
                aria-hidden="true"
            >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
            </svg>
        </button>

        <div
            id="editor-section-content"
            className={`editor-collapse ${isExpanded ? 'editor-collapse-open' : ''}`}
        >
            <div className="editor-collapse-inner">
                <div className="editor-section-body">
                    {!selectedJob || selectedJob.status !== 'completed' ? (
                        <div className="editor-empty-state">
                            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M15 10l4.5-2.25A1 1 0 0121 8.65v6.7a1 1 0 01-1.5.9L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                            <p>{t('resultPreviewTitle')}</p>
                            <span>{t('resultPreviewDescription')}</span>
                        </div>
                    ) : (
                        <>
                            <div className="editor-ready-header">
                                <div>
                                    <span className="editor-ready-kicker">{t('statusReady')}</span>
                                    <h2>{t('subtitlesReady')}</h2>
                                    <p>{t('liveOutputSubtitle')}</p>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => setShowNewVideoModal(true)}
                                    className="editor-new-video"
                                >
                                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 5v14m7-7H5" />
                                    </svg>
                                    <span>{t('newVideoButton')}</span>
                                </button>
                            </div>

                            {!isProcessing && (
                                <div className="editor-product animate-fade-in" data-testid="completed-editor">
                                    <div className="editor-workspace" data-testid="editor-workspace">
                                        <section
                                            className="editor-preview-panel"
                                            data-testid="editor-preview-panel"
                                            aria-label={t('previewWindowLabel')}
                                        >
                                            <div className="editor-preview-meta">
                                                {(selectedJob.result_data?.transcribe_provider || transcribeProvider) && (
                                                    <span className="editor-model-pill">
                                                        {displayedModel && <span aria-hidden="true">{displayedModel.icon(true)}</span>}
                                                        <span>{displayedModel?.name || 'Standard'}</span>
                                                    </span>
                                                )}
                                                <span className="editor-aspect-pill">9:16</span>
                                            </div>

                                            <div className="editor-phone" data-testid="editor-phone">
                                                <PhoneFrame className="h-full w-full" showSocialOverlays={false}>
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
                                                        <div className="editor-preview-placeholder">
                                                            <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
                                                                <path d="M8.5 6.9a1 1 0 011.52-.85l7.3 4.6a1 1 0 010 1.7l-7.3 4.6a1 1 0 01-1.52-.85V6.9z" />
                                                            </svg>
                                                            <span>{t('clickToPreview')}</span>
                                                        </div>
                                                    )}
                                                </PhoneFrame>
                                            </div>
                                        </section>

                                        <Sidebar />
                                    </div>

                                    <section className="editor-export-panel" aria-labelledby="editor-export-title">
                                        <div className="editor-export-heading">
                                            <h3 id="editor-export-title">{t('stepExport')}</h3>
                                            <span>MP4 · SRT · VTT · TXT</span>
                                        </div>

                                        <div className="editor-export-grid" data-testid="editor-export-grid">
                                            {EXPORT_OPTIONS.map((option) => (
                                                <ExportAction
                                                    key={option.resolution}
                                                    option={option}
                                                    isExporting={Boolean(exportingResolutions[option.resolution])}
                                                    onExport={handleExport}
                                                    t={t}
                                                />
                                            ))}
                                        </div>

                                        {exportError && (
                                            <p className="editor-export-error" role="alert">
                                                {exportError}
                                            </p>
                                        )}
                                    </section>
                                </div>
                            )}
                        </>
                    )}

                    <NewVideoConfirmModal
                        isOpen={showNewVideoModal}
                        onClose={() => setShowNewVideoModal(false)}
                        onConfirm={onNewVideoConfirm}
                    />
                </div>
            </div>
        </div>
    </div>
));
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
        exportError,
        onReset,
        setHasChosenModel,
        onJobSelect,
    } = useProcessContext();
    const { setCurrentTime } = usePlaybackContext();
    const [showNewVideoModal, setShowNewVideoModal] = React.useState(false);
    const [localCollapsed, setLocalCollapsed] = React.useState(false);

    React.useEffect(() => {
        if (currentStep !== 3) {
            setLocalCollapsed(false);
        }
    }, [currentStep]);

    const isExpanded = currentStep === 3 && !localCollapsed;

    const handleNewVideoConfirm = useCallback(() => {
        onReset();
        setHasChosenModel(true);
        onJobSelect(null);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }, [onReset, setHasChosenModel, onJobSelect]);

    const playerSettings = useMemo(() => ({
        position: subtitlePosition,
        color: subtitleColor,
        fontSize: subtitleSize,
        karaoke: karaokeEnabled,
        maxLines: maxSubtitleLines,
        shadowStrength,
        watermarkEnabled,
    }), [subtitlePosition, subtitleColor, subtitleSize, karaokeEnabled, maxSubtitleLines, shadowStrength, watermarkEnabled]);

    const handlePlayerTimeUpdate = useCallback((time: number) => {
        setCurrentTime(time);
    }, [setCurrentTime]);

    const handleStepClick = useCallback(() => {
        if (currentStep === 3) {
            setLocalCollapsed((collapsed) => !collapsed);
            return;
        }

        setOverrideStep(3);
        setLocalCollapsed(false);
        setTimeout(() => {
            document.getElementById('step-3-wrapper')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 350);
    }, [currentStep, setOverrideStep]);

    const displayedModel = useMemo(() => {
        if (selectedJob?.status === 'completed' && selectedJob.result_data) {
            const jobTier = resolveTranscriptionTier(
                selectedJob.result_data.transcribe_provider,
                selectedJob.result_data.model_size,
            );
            return AVAILABLE_MODELS.find((model) => model.mode === jobTier);
        }

        return AVAILABLE_MODELS.find(
            (model) => model.provider === transcribeProvider && model.mode === transcribeMode,
        );
    }, [AVAILABLE_MODELS, selectedJob, transcribeProvider, transcribeMode]);

    return (
        <PreviewSectionLayout
            resultsRef={resultsRef}
            currentStep={currentStep}
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
            exportError={exportError}
            showNewVideoModal={showNewVideoModal}
            setShowNewVideoModal={setShowNewVideoModal}
            onNewVideoConfirm={handleNewVideoConfirm}
            isExpanded={isExpanded}
        />
    );
}
