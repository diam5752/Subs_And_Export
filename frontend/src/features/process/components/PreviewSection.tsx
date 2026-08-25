import React, { memo, useCallback, useMemo } from 'react';
import { PhoneFrame } from '@/components/PhoneFrame';
import {
    PreviewPlayer,
    type InlineSubtitleEditorConfig,
    type PreviewPlayerHandle,
    type SubtitleTransformConfig,
} from '@/components/PreviewPlayer';
import { Spinner } from '@/components/Spinner';
import { useI18n } from '@/context/I18nContext';
import type { MessageKey } from '@/context/i18nMessages';
import type { JobResponse } from '@/lib/api';
import { usePlaybackContext } from '../PlaybackContext';
import { useProcessContext } from '../ProcessContext';
import { buildSubtitleExportFilename } from '@/lib/exportFilename';
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
    handleExport: (resolution: string) => Promise<void>;
    exportingResolutions: Record<string, boolean>;
    exportError: string | null;
    activeSidebarTab: 'transcript' | 'styles' | 'intelligence';
    exportFilenamePreview: string;
    showNewVideoModal: boolean;
    setShowNewVideoModal: React.Dispatch<React.SetStateAction<boolean>>;
    showExportMenu: boolean;
    setShowExportMenu: React.Dispatch<React.SetStateAction<boolean>>;
    exportTriggerRef: React.RefObject<HTMLButtonElement | null>;
    onNewVideoConfirm: () => void;
};

type ExportOption = {
    resolution: '720x1280' | '1080x1920' | 'srt' | 'txt' | '2160x3840';
    label: string;
    descriptionKey: MessageKey;
    loadingKey: MessageKey;
    testId: string;
    primary?: boolean;
};

const VIDEO_EXPORT_OPTIONS: ExportOption[] = [
    {
        resolution: '720x1280',
        label: '720p Fast',
        descriptionKey: 'exportFastDesc',
        loadingKey: 'exportRendering',
        testId: 'download-720p-btn',
        primary: true,
    },
    {
        resolution: '1080x1920',
        label: '1080p',
        descriptionKey: 'exportHdDesc',
        loadingKey: 'exportRendering',
        testId: 'download-1080p-btn',
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
        resolution: 'txt',
        label: 'TXT',
        descriptionKey: 'subtitleFileTxtDesc',
        loadingKey: 'exportSaving',
        testId: 'txt-btn',
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

const ExportMenu = memo(({
    isOpen,
    onClose,
    triggerRef,
    exportingResolutions,
    onExport,
    exportFilenamePreview,
    exportError,
    t,
}: {
    isOpen: boolean;
    onClose: () => void;
    triggerRef: React.RefObject<HTMLButtonElement | null>;
    exportingResolutions: Record<string, boolean>;
    onExport: (resolution: string) => Promise<void>;
    exportFilenamePreview: string;
    exportError: string | null;
    t: PreviewSectionLayoutProps['t'];
}) => {
    const menuRef = React.useRef<HTMLElement>(null);

    React.useEffect(() => {
        if (!isOpen) return;

        const triggerElement = triggerRef.current;
        const focusFrame = window.requestAnimationFrame(() => {
            menuRef.current?.focus();
        });
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                onClose();
            }
        };
        document.addEventListener('keydown', handleKeyDown);

        return () => {
            window.cancelAnimationFrame(focusFrame);
            document.removeEventListener('keydown', handleKeyDown);
            triggerElement?.focus();
        };
    }, [isOpen, onClose, triggerRef]);

    const handleExportSelection = useCallback(async (resolution: string) => {
        onClose();
        await onExport(resolution);
    }, [onClose, onExport]);

    if (!isOpen) return null;

    return (
        <>
            <button
                type="button"
                className="editor-export-backdrop"
                aria-label={t('closeLabel')}
                tabIndex={-1}
                onClick={onClose}
            />
            <section
                ref={menuRef}
                id="editor-export-menu"
                className="editor-export-menu"
                role="dialog"
                tabIndex={-1}
                aria-modal="true"
                aria-labelledby="editor-export-menu-title"
                aria-describedby="editor-export-menu-description"
                data-testid="editor-export-menu"
            >
                <span className="editor-export-menu-handle" aria-hidden="true" />
                <header className="editor-export-menu-header">
                    <div>
                        <h2 id="editor-export-menu-title">{t('stepExport')}</h2>
                        <p id="editor-export-menu-description">{t('exportMenuDescription')}</p>
                    </div>
                    <button
                        type="button"
                        className="editor-export-menu-close"
                        aria-label={t('closeLabel')}
                        onClick={onClose}
                    >
                        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M6 6l12 12M18 6L6 18" />
                        </svg>
                    </button>
                </header>

                <div className="editor-export-groups" data-testid="editor-export-grid">
                    <ExportGroup
                        titleKey="exportVideoTitle"
                        formats="MP4"
                        options={VIDEO_EXPORT_OPTIONS}
                        variant="video"
                        testId="video-export-group"
                        exportingResolutions={exportingResolutions}
                        onExport={handleExportSelection}
                        t={t}
                    />
                    <ExportGroup
                        titleKey="exportSubtitlesTitle"
                        formats="SRT · TXT"
                        options={SUBTITLE_EXPORT_OPTIONS}
                        variant="subtitles"
                        testId="subtitle-export-group"
                        exportingResolutions={exportingResolutions}
                        onExport={handleExportSelection}
                        t={t}
                    />
                </div>

                <p className="editor-export-filename" data-testid="export-filename-preview">
                    <span>{t('exportFilenameLabel')}</span>
                    <strong title={exportFilenamePreview}>{exportFilenamePreview}</strong>
                </p>
                <p className="editor-export-retention-note">
                    <span aria-hidden="true">↻</span>
                    {t('temporaryWorkspaceExportNote')}
                </p>

                {exportError && (
                    <p className="editor-export-error" role="alert">
                        {exportError}
                    </p>
                )}
            </section>
        </>
    );
});
ExportMenu.displayName = 'ExportMenu';

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
    handleExport,
    exportingResolutions,
    exportError,
    activeSidebarTab,
    exportFilenamePreview,
    showNewVideoModal,
    setShowNewVideoModal,
    showExportMenu,
    setShowExportMenu,
    exportTriggerRef,
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
                            <div className="editor-ready-actions">
                                <button
                                    type="button"
                                    onClick={() => {
                                        setShowExportMenu(false);
                                        setShowNewVideoModal(true);
                                    }}
                                    className="editor-new-video"
                                >
                                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 5v14m7-7H5" />
                                    </svg>
                                    <span>{t('newVideoButton')}</span>
                                </button>
                                <button
                                    ref={exportTriggerRef}
                                    type="button"
                                    className="editor-export-trigger"
                                    aria-haspopup="dialog"
                                    aria-expanded={showExportMenu}
                                    aria-controls="editor-export-menu"
                                    aria-busy={Object.values(exportingResolutions).some(Boolean)}
                                    disabled={Object.values(exportingResolutions).some(Boolean)}
                                    onClick={() => setShowExportMenu((isOpen) => !isOpen)}
                                >
                                    {Object.values(exportingResolutions).some(Boolean) ? (
                                        <Spinner className="h-4 w-4" />
                                    ) : (
                                        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M12 3v12m0 0l-4-4m4 4l4-4M5 19h14" />
                                        </svg>
                                    )}
                                    <span>{t('exportMenuButton')}</span>
                                </button>

                                <ExportMenu
                                    isOpen={showExportMenu}
                                    onClose={() => setShowExportMenu(false)}
                                    triggerRef={exportTriggerRef}
                                    exportingResolutions={exportingResolutions}
                                    onExport={handleExport}
                                    exportFilenamePreview={exportFilenamePreview}
                                    exportError={exportError}
                                    t={t}
                                />
                            </div>

                            {!isProcessing && (
                                <div className="editor-product animate-fade-in" data-testid="completed-editor">
                                    <div
                                        id="editor-workspace"
                                        className={`editor-workspace ${
                                            activeSidebarTab === 'styles'
                                                ? 'editor-workspace-style-mode'
                                                : ''
                                        }`}
                                        data-editor-mode={activeSidebarTab}
                                        data-testid="editor-workspace"
                                    >
                                        <section
                                            className="editor-preview-panel"
                                            data-testid="editor-preview-panel"
                                            aria-label={t('previewWindowLabel')}
                                        >
                                            <div className="editor-preview-stage">
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
                                            </div>
                                        </section>

                                        <Sidebar />
                                    </div>
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
        activeSidebarTab,
        beginEditingCue,
        handleUpdateDraft,
        saveEditingCue,
        cancelEditingCue,
    } = useProcessContext();
    const { setCurrentTime } = usePlaybackContext();
    const [showNewVideoModal, setShowNewVideoModal] = React.useState(false);
    const [showExportMenu, setShowExportMenu] = React.useState(false);
    const exportTriggerRef = React.useRef<HTMLButtonElement>(null);
    const originalFilename = selectedJob?.result_data?.original_filename;
    const exportFilenamePreview = useMemo(
        () => buildSubtitleExportFilename(originalFilename, 'mp4'),
        [originalFilename],
    );

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
            handleExport={handleExport}
            exportingResolutions={exportingResolutions}
            exportError={exportError}
            activeSidebarTab={activeSidebarTab}
            exportFilenamePreview={exportFilenamePreview}
            showNewVideoModal={showNewVideoModal}
            setShowNewVideoModal={setShowNewVideoModal}
            showExportMenu={showExportMenu}
            setShowExportMenu={setShowExportMenu}
            exportTriggerRef={exportTriggerRef}
            onNewVideoConfirm={handleNewVideoConfirm}
        />
    );
}
