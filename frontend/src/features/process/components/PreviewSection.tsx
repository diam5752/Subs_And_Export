import React, { memo, useCallback, useMemo } from 'react';
import { PhoneFrame } from '@/components/PhoneFrame';
import {
    PreviewPlayer,
    type InlineSubtitleEditorConfig,
    type PreviewPlaybackStatus,
    type PreviewPlayerHandle,
    type SubtitleTransformConfig,
} from '@/components/PreviewPlayer';
import { Spinner } from '@/components/Spinner';
import { useI18n } from '@/context/I18nContext';
import type { MessageKey } from '@/context/i18nMessages';
import type { JobResponse } from '@/lib/api';
import { usePlaybackContext } from '../PlaybackContext';
import { useProcessContext } from '../ProcessContext';
import { NewVideoConfirmModal } from './NewVideoConfirmModal';
import { Sidebar } from './Sidebar';

type PreviewSectionLayoutProps = {
    resultsRef: React.RefObject<HTMLDivElement | null>;
    selectedJob: JobResponse | null;
    isProcessing: boolean;
    t: (key: MessageKey, params?: Record<string, string | number>) => string;
    processedCues: React.ComponentProps<typeof PreviewPlayer>['cues'];
    playerRef: React.RefObject<PreviewPlayerHandle | null>;
    videoUrl: string | null;
    playerSettings: React.ComponentProps<typeof PreviewPlayer>['settings'];
    subtitleEditor: InlineSubtitleEditorConfig;
    subtitleTransformControls: SubtitleTransformConfig;
    handlePlayerTimeUpdate: (time: number) => void;
    playbackStatus: PreviewPlaybackStatus;
    currentTime: number;
    onPlaybackStatusChange: (status: PreviewPlaybackStatus) => void;
    onTogglePlayback: () => void;
    onToggleMuted: () => void;
    onSeek: (time: number) => void;
    handleExport: (resolution: string) => Promise<void>;
    exportingResolutions: Record<string, boolean>;
    exportError: string | null;
    showNewVideoModal: boolean;
    setShowNewVideoModal: React.Dispatch<React.SetStateAction<boolean>>;
    onNewVideoConfirm: () => void;
};

type ExportOption = {
    resolution: '1080x1920' | 'srt' | 'vtt' | 'txt' | '2160x3840';
    label: string;
    descriptionKey: MessageKey;
    loadingKey: MessageKey;
    testId: string;
    primary?: boolean;
};

const VIDEO_EXPORT_OPTIONS: ExportOption[] = [
    {
        resolution: '1080x1920',
        label: '1080p',
        descriptionKey: 'exportHdDesc',
        loadingKey: 'exportRendering',
        testId: 'download-1080p-btn',
        primary: true,
    },
    {
        resolution: '2160x3840',
        label: '4K',
        descriptionKey: 'export4kDesc',
        loadingKey: 'exportMastering',
        testId: 'download-4k-btn',
    },
];

const SUBTITLE_EXPORT_OPTIONS: ExportOption[] = [
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
];

export function formatPlaybackTime(seconds: number): string {
    const safeSeconds = Number.isFinite(seconds) && seconds > 0
        ? Math.floor(seconds)
        : 0;
    const hours = Math.floor(safeSeconds / 3600);
    const minutes = Math.floor((safeSeconds % 3600) / 60);
    const remainingSeconds = safeSeconds % 60;

    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${remainingSeconds
            .toString()
            .padStart(2, '0')}`;
    }
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
}

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

const ExportGroup = memo(({
    titleKey,
    formats,
    options,
    variant,
    testId,
    exportingResolutions,
    onExport,
    t,
}: {
    titleKey: MessageKey;
    formats: string;
    options: ExportOption[];
    variant: 'video' | 'subtitles';
    testId: 'video-export-group' | 'subtitle-export-group';
    exportingResolutions: Record<string, boolean>;
    onExport: (resolution: string) => Promise<void>;
    t: PreviewSectionLayoutProps['t'];
}) => {
    const headingId = `${testId}-title`;

    return (
        <section
            className="editor-export-group"
            aria-labelledby={headingId}
            data-testid={testId}
        >
            <div className="editor-export-group-heading">
                <h3 id={headingId}>{t(titleKey)}</h3>
                <span>{formats}</span>
            </div>

            <div className={`editor-export-grid editor-export-grid-${variant}`}>
                {options.map((option) => (
                    <ExportAction
                        key={option.resolution}
                        option={option}
                        isExporting={Boolean(exportingResolutions[option.resolution])}
                        onExport={onExport}
                        t={t}
                    />
                ))}
            </div>
        </section>
    );
});
ExportGroup.displayName = 'ExportGroup';

const PreviewSectionLayout = memo(({
    resultsRef,
    selectedJob,
    isProcessing,
    t,
    processedCues,
    playerRef,
    videoUrl,
    playerSettings,
    subtitleEditor,
    subtitleTransformControls,
    handlePlayerTimeUpdate,
    playbackStatus,
    currentTime,
    onPlaybackStatusChange,
    onTogglePlayback,
    onToggleMuted,
    onSeek,
    handleExport,
    exportingResolutions,
    exportError,
    showNewVideoModal,
    setShowNewVideoModal,
    onNewVideoConfirm,
}: PreviewSectionLayoutProps) => (
    <div
        id="preview-section"
        className={`card editor-section ${!selectedJob && !isProcessing ? 'opacity-50 grayscale' : ''}`}
        ref={resultsRef}
    >
        <div id="editor-section-content">
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
                                            <div className="editor-phone" data-testid="editor-phone">
                                                <PhoneFrame className="h-full w-full" showSocialOverlays={false}>
                                                    {videoUrl ? (
                                                        <PreviewPlayer
                                                            ref={playerRef}
                                                            videoUrl={videoUrl}
                                                            cues={processedCues || []}
                                                            settings={playerSettings}
                                                            subtitleEditor={subtitleEditor}
                                                            subtitleTransformControls={subtitleTransformControls}
                                                            onTimeUpdate={handlePlayerTimeUpdate}
                                                            onPlaybackStatusChange={onPlaybackStatusChange}
                                                            playbackToggleLabel={t('previewVideoToggle')}
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
                                            {videoUrl && (
                                                <>
                                                    <div
                                                        className="editor-preview-controls"
                                                        data-testid="editor-preview-controls"
                                                    >
                                                        <input
                                                            type="range"
                                                            className="editor-preview-scrubber"
                                                            min={0}
                                                            max={Math.max(playbackStatus.duration, 0)}
                                                            step={0.1}
                                                            value={Math.min(currentTime, playbackStatus.duration || 0)}
                                                            disabled={playbackStatus.duration <= 0}
                                                            aria-label={t('seekVideo')}
                                                            onChange={(event) => onSeek(Number(event.currentTarget.value))}
                                                        />
                                                        <div className="editor-preview-control-row">
                                                            <button
                                                                type="button"
                                                                className="editor-preview-control-button"
                                                                aria-label={t(playbackStatus.isPlaying ? 'pausePreview' : 'playPreview')}
                                                                onClick={onTogglePlayback}
                                                            >
                                                                {playbackStatus.isPlaying ? (
                                                                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
                                                                        <path d="M7 5h3.5v14H7V5zm6.5 0H17v14h-3.5V5z" />
                                                                    </svg>
                                                                ) : (
                                                                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
                                                                        <path d="M8 5.5v13l10-6.5L8 5.5z" />
                                                                    </svg>
                                                                )}
                                                            </button>
                                                            <output
                                                                className="editor-preview-time"
                                                                data-testid="editor-preview-time"
                                                                aria-label={t('previewTimeLabel')}
                                                                aria-live="off"
                                                            >
                                                                {formatPlaybackTime(Math.min(
                                                                    Math.max(currentTime, 0),
                                                                    playbackStatus.duration || 0,
                                                                ))}
                                                                {' / '}
                                                                {formatPlaybackTime(playbackStatus.duration)}
                                                            </output>
                                                            <button
                                                                type="button"
                                                                className="editor-preview-control-button"
                                                                aria-label={t(playbackStatus.isMuted ? 'unmutePreview' : 'mutePreview')}
                                                                onClick={onToggleMuted}
                                                            >
                                                                {playbackStatus.isMuted ? (
                                                                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5 6.8 8.5H4v7h2.8L11 19V5Zm4.5 5.2 4 4m0-4-4 4" />
                                                                    </svg>
                                                                ) : (
                                                                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5 6.8 8.5H4v7h2.8L11 19V5Zm4 3.5a5 5 0 0 1 0 7m2.5-9.5a8.5 8.5 0 0 1 0 12" />
                                                                    </svg>
                                                                )}
                                                            </button>
                                                        </div>
                                                    </div>
                                                    <p
                                                        data-testid="subtitle-direct-manipulation-hint"
                                                        className="mt-4 max-w-[278px] text-center text-[11px] font-semibold leading-5 text-[var(--muted)]"
                                                    >
                                                        <span className="subtitle-desktop-manipulation-hint">
                                                            <span aria-hidden="true" className="mr-1 text-[var(--accent)]">↕</span>
                                                            {t('subtitleDirectManipulationHint')}
                                                        </span>
                                                        <span
                                                            className="subtitle-touch-manipulation-hint"
                                                            data-testid="subtitle-touch-manipulation-hint"
                                                        >
                                                            <span aria-hidden="true" className="mr-1 text-[var(--accent)]">↕</span>
                                                            {t('subtitleTouchManipulationHint')}
                                                        </span>
                                                    </p>
                                                </>
                                            )}
                                        </section>

                                        <Sidebar />
                                    </div>

                                    <section className="editor-export-panel" aria-label={t('stepExport')}>
                                        <div className="editor-export-groups" data-testid="editor-export-grid">
                                            <ExportGroup
                                                titleKey="exportVideoTitle"
                                                formats="MP4"
                                                options={VIDEO_EXPORT_OPTIONS}
                                                variant="video"
                                                testId="video-export-group"
                                                exportingResolutions={exportingResolutions}
                                                onExport={handleExport}
                                                t={t}
                                            />
                                            <ExportGroup
                                                titleKey="exportSubtitlesTitle"
                                                formats="SRT · VTT · TXT"
                                                options={SUBTITLE_EXPORT_OPTIONS}
                                                variant="subtitles"
                                                testId="subtitle-export-group"
                                                exportingResolutions={exportingResolutions}
                                                onExport={handleExport}
                                                t={t}
                                            />
                                        </div>
                                        <p className="mt-4 text-center text-[11px] font-medium leading-5 text-[var(--muted)]">
                                            <span aria-hidden="true" className="mr-1.5 text-[var(--accent)]">↻</span>
                                            {t('temporaryWorkspaceExportNote')}
                                        </p>

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
));
PreviewSectionLayout.displayName = 'PreviewSectionLayout';

export function PreviewSection() {
    const { t } = useI18n();
    const {
        selectedJob,
        isProcessing,
        videoUrl,
        processedCues,
        cues,
        subtitlePosition,
        setSubtitlePosition,
        subtitleColor,
        subtitleSize,
        setSubtitleSize,
        karaokeEnabled,
        maxSubtitleLines,
        shadowStrength,
        watermarkEnabled,
        playerRef,
        resultsRef,
        handleExport,
        exportingResolutions,
        exportError,
        onReset,
        onJobSelect,
        editingCueIndex,
        editingCueDraft,
        editingCueSurface,
        isSavingTranscript,
        transcriptSaveError,
        beginEditingCue,
        handleUpdateDraft,
        saveEditingCue,
        cancelEditingCue,
    } = useProcessContext();
    const { currentTime, setCurrentTime } = usePlaybackContext();
    const [showNewVideoModal, setShowNewVideoModal] = React.useState(false);
    const [playbackStatus, setPlaybackStatus] = React.useState<PreviewPlaybackStatus>({
        duration: 0,
        isPlaying: false,
        isMuted: false,
    });

    const handleNewVideoConfirm = useCallback(() => {
        onReset();
        onJobSelect(null);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }, [onReset, onJobSelect]);

    const playerSettings = useMemo(() => ({
        position: subtitlePosition,
        color: subtitleColor,
        fontSize: subtitleSize,
        karaoke: karaokeEnabled,
        maxLines: maxSubtitleLines,
        shadowStrength,
        watermarkEnabled,
    }), [subtitlePosition, subtitleColor, subtitleSize, karaokeEnabled, maxSubtitleLines, shadowStrength, watermarkEnabled]);

    const subtitleEditor = useMemo<InlineSubtitleEditorConfig>(() => ({
        cues,
        editingCueIndex,
        draftText: editingCueDraft,
        isSaving: isSavingTranscript,
        error: transcriptSaveError,
        autoFocus: editingCueSurface === 'video',
        labels: {
            editAction: t('subtitleInlineEditAction'),
            title: t('subtitleInlineEditorTitle'),
            textarea: t('subtitleInlineTextareaLabel'),
            save: t('transcriptSave'),
            cancel: t('transcriptCancel'),
            shortcut: t('transcriptEditHint'),
            saving: t('transcriptSaving'),
        },
        onBeginEdit: (index) => beginEditingCue(index, 'video'),
        onChange: handleUpdateDraft,
        onSave: saveEditingCue,
        onCancel: cancelEditingCue,
    }), [
        beginEditingCue,
        cancelEditingCue,
        cues,
        editingCueDraft,
        editingCueIndex,
        editingCueSurface,
        handleUpdateDraft,
        isSavingTranscript,
        saveEditingCue,
        t,
        transcriptSaveError,
    ]);

    const subtitleTransformControls = useMemo<SubtitleTransformConfig>(() => ({
        labels: {
            move: t('subtitleDragHandleLabel'),
            resize: t('subtitleResizeHandleLabel'),
        },
        onPositionChange: setSubtitlePosition,
        onSizeChange: setSubtitleSize,
    }), [setSubtitlePosition, setSubtitleSize, t]);

    const handlePlayerTimeUpdate = useCallback((time: number) => {
        setCurrentTime(time);
    }, [setCurrentTime]);

    const handleSeek = useCallback((time: number) => {
        playerRef.current?.seekTo(time);
        setCurrentTime(time);
    }, [playerRef, setCurrentTime]);

    const handleTogglePlayback = useCallback(() => {
        playerRef.current?.togglePlayback();
    }, [playerRef]);

    const handleToggleMuted = useCallback(() => {
        playerRef.current?.toggleMuted();
    }, [playerRef]);

    return (
        <PreviewSectionLayout
            resultsRef={resultsRef}
            selectedJob={selectedJob}
            isProcessing={isProcessing}
            t={t}
            processedCues={processedCues}
            playerRef={playerRef}
            videoUrl={videoUrl}
            playerSettings={playerSettings}
            subtitleEditor={subtitleEditor}
            subtitleTransformControls={subtitleTransformControls}
            handlePlayerTimeUpdate={handlePlayerTimeUpdate}
            playbackStatus={playbackStatus}
            currentTime={currentTime}
            onPlaybackStatusChange={setPlaybackStatus}
            onTogglePlayback={handleTogglePlayback}
            onToggleMuted={handleToggleMuted}
            onSeek={handleSeek}
            handleExport={handleExport}
            exportingResolutions={exportingResolutions}
            exportError={exportError}
            showNewVideoModal={showNewVideoModal}
            setShowNewVideoModal={setShowNewVideoModal}
            onNewVideoConfirm={handleNewVideoConfirm}
        />
    );
}
