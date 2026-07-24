import React, { useCallback, useEffect, useMemo, memo } from 'react';
import { Spinner } from '@/components/Spinner';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { usePlaybackContext } from '../PlaybackContext';
import { CueItem } from '../CueItem';
import { Cue } from '@/components/SubtitleOverlay';
import { findCueIndexAtTime } from '@/lib/subtitleUtils';
import { SubtitlePositionSelector } from '@/components/SubtitlePositionSelector';
import { ViralIntelligence } from '@/components/ViralIntelligence';
import { StylePresetTiles } from './StylePresetTiles';
import type { StylePreset } from '../processTypes';

interface CueListProps {
    cues: Cue[];
    activeCueIndex: number;
    editingCueIndex: number | null;
    editingCueDraft: string;
    isSaving: boolean;
    onSeek: (time: number) => void;
    onEdit: (index: number) => void;
    onSave: () => void;
    onCancel: () => void;
    onUpdateDraft: (text: string) => void;
    autoFocusEditor: boolean;
}

const CueList = memo(({
    cues,
    activeCueIndex,
    editingCueIndex,
    editingCueDraft,
    isSaving,
    onSeek,
    onEdit,
    onSave,
    onCancel,
    onUpdateDraft,
    autoFocusEditor,
}: CueListProps) => {
    return (
        <>
            {cues.map((cue, index) => {
                const isActive = index === activeCueIndex;
                const isEditing = editingCueIndex === index;
                const canEditThis = !isSaving && (editingCueIndex === null || isEditing);

                return (
                    <div id={`cue-${index}`} key={`${cue.start}-${cue.end}-${index}`}>
                        <CueItem
                            cue={cue}
                            index={index}
                            isActive={isActive}
                            isEditing={isEditing}
                            canEdit={canEditThis}
                            draftText={isEditing ? editingCueDraft : ''}
                            isSaving={isSaving}
                            onSeek={onSeek}
                            onEdit={onEdit}
                            onSave={onSave}
                            onCancel={onCancel}
                            onUpdateDraft={onUpdateDraft}
                            autoFocusEditor={autoFocusEditor}
                        />
                    </div>
                );
            })}
        </>
    );
});
CueList.displayName = 'CueList';

const TranscriptPanel = memo(() => {
    const { t } = useI18n();
    const {
        cues,
        editingCueIndex,
        editingCueDraft,
        editingCueSurface,
        isSavingTranscript,
        transcriptLoadError,
        transcriptSaveError,
        transcriptContainerRef,
        playerRef,
        handleUpdateDraft,
        beginEditingCue,
        saveEditingCue,
        cancelEditingCue,
        isProcessing // Added from context
    } = useProcessContext();
    const { currentTime } = usePlaybackContext();

    const handleSeek = useCallback((time: number) => {
        playerRef.current?.seekTo(time);
    }, [playerRef]);

    const handleEdit = useCallback((index: number) => {
        const cue = cues[index];
        if (!cue) return;
        playerRef.current?.pause();
        playerRef.current?.seekTo(cue.start);
        beginEditingCue(index, 'transcript');
    }, [beginEditingCue, cues, playerRef]);

    const activeCueIndex = useMemo(() => {
        if (!cues || cues.length === 0) return -1;
        return findCueIndexAtTime(cues, currentTime);
    }, [cues, currentTime]);

    // Scroll active cue into view
    useEffect(() => {
        if (editingCueIndex !== null) return;
        if (activeCueIndex === -1) return;

        if (transcriptContainerRef.current) {
            const element = document.getElementById(`cue-${activeCueIndex}`);
            const container = transcriptContainerRef.current;

            if (element) {
                const elementTop = element.offsetTop;
                const elementHeight = element.offsetHeight;
                const containerHeight = container.clientHeight;
                const targetScroll = elementTop - (containerHeight / 2) + (elementHeight / 2);

                container.scrollTo({
                    top: targetScroll,
                    behavior: 'smooth'
                });
            }
        }
    }, [activeCueIndex, editingCueIndex, transcriptContainerRef]);

    // Optimized: Memoize the JSX to prevent VDOM re-creation on every frame (60fps)
    // TranscriptPanel re-renders on every currentTime update, but the VDOM structure
    // should only change when relevant state (activeCueIndex, editing state) changes.
    return useMemo(() => (
        <div
            role="tabpanel"
            id="panel-transcript"
            aria-labelledby="tab-transcript"
            className="space-y-2"
        >
            {transcriptLoadError && (
                <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    {transcriptLoadError}
                </div>
            )}
            {transcriptSaveError && (
                <div className="rounded-lg border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-3 py-2 text-xs text-[var(--danger)]">
                    {transcriptSaveError}
                </div>
            )}
            {isSavingTranscript && (
                <div className="flex items-center gap-2 px-1 text-xs text-[var(--muted)]">
                    <Spinner className="w-3.5 h-3.5 text-[var(--muted)]" />
                    {t('transcriptSaving') || 'Saving…'}
                </div>
            )}

            {/* Scrollable Transcript List */}
            <div
                ref={transcriptContainerRef}
                className="editor-transcript-list custom-scrollbar scroll-smooth"
            >
                <CueList
                    cues={cues}
                    activeCueIndex={activeCueIndex}
                    editingCueIndex={editingCueIndex}
                    editingCueDraft={editingCueDraft}
                    isSaving={isSavingTranscript}
                    onSeek={handleSeek}
                    onEdit={handleEdit}
                    onSave={saveEditingCue}
                    onCancel={cancelEditingCue}
                    onUpdateDraft={handleUpdateDraft}
                    autoFocusEditor={editingCueSurface !== 'video'}
                />
                {cues.length === 0 && (
                    <div className="text-center text-[var(--muted)] py-10 opacity-50 font-medium">
                        {isProcessing
                            ? (t('statusProcessing') || 'Processing...')
                            : (t('noSubtitlesFound') || 'No subtitles found in this video.')}
                    </div>
                )}
            </div>
        </div>
    ), [
        activeCueIndex,
        cues,
        editingCueIndex,
        editingCueDraft,
        editingCueSurface,
        isSavingTranscript,
        transcriptLoadError,
        transcriptSaveError,
        transcriptContainerRef,
        handleSeek,
        handleEdit,
        saveEditingCue,
        cancelEditingCue,
        handleUpdateDraft,
        t,
        isProcessing
    ]);
});
TranscriptPanel.displayName = 'TranscriptPanel';

export function Sidebar() {
    const { t } = useI18n();
    const {
        selectedJob,
        isProcessing,
        progress,
        activeSidebarTab,
        setActiveSidebarTab,
        STYLE_PRESETS,
        activePreset,
        setActivePreset,
        setSubtitlePosition,
        setSubtitleSize,
        setMaxSubtitleLines,
        setSubtitleColor,
        setKaraokeEnabled,
        lastUsedSettings,
        subtitlePosition,
        maxSubtitleLines,
        subtitleColor,
        SUBTITLE_COLORS,
        subtitleSize,
        karaokeEnabled,
        watermarkEnabled,
        setWatermarkEnabled,
    } = useProcessContext();

    // Stable callbacks for StylePresetTiles
    const handlePresetSelect = useCallback((preset: StylePreset) => {
        setActivePreset(preset.id);
        setSubtitlePosition(preset.settings.position as number);
        setSubtitleSize(preset.settings.size);
        setMaxSubtitleLines(preset.settings.lines);
        setSubtitleColor(preset.settings.color);
        setKaraokeEnabled(preset.settings.karaoke);
    }, [setActivePreset, setSubtitlePosition, setSubtitleSize, setMaxSubtitleLines, setSubtitleColor, setKaraokeEnabled]);

    const handleLastUsedSelect = useCallback(() => {
        if (!lastUsedSettings) return;
        setActivePreset('lastUsed');
        setSubtitlePosition(lastUsedSettings.position);
        setSubtitleSize(lastUsedSettings.size);
        setMaxSubtitleLines(lastUsedSettings.lines);
        setSubtitleColor(lastUsedSettings.color);
        setKaraokeEnabled(lastUsedSettings.karaoke);
        setWatermarkEnabled(lastUsedSettings.watermark ?? false);
    }, [lastUsedSettings, setActivePreset, setSubtitlePosition, setSubtitleSize, setMaxSubtitleLines, setSubtitleColor, setKaraokeEnabled, setWatermarkEnabled]);

    // Stable callbacks for SubtitlePositionSelector
    const handlePositionChange = useCallback((v: number) => { setSubtitlePosition(v); setActivePreset(null); }, [setSubtitlePosition, setActivePreset]);
    const handleLinesChange = useCallback((v: number) => { setMaxSubtitleLines(v); setActivePreset(null); }, [setMaxSubtitleLines, setActivePreset]);
    const handleColorChange = useCallback((v: string) => { setSubtitleColor(v); setActivePreset(null); }, [setSubtitleColor, setActivePreset]);
    const handleSizeChange = useCallback((v: number) => { setSubtitleSize(v); setActivePreset(null); }, [setSubtitleSize, setActivePreset]);
    const handleKaraokeChange = useCallback((enabled: boolean) => {
        setKaraokeEnabled(enabled);
        setActivePreset(null);
    }, [setKaraokeEnabled, setActivePreset]);

    const handleWatermarkChange = useCallback((enabled: boolean) => {
        setWatermarkEnabled(enabled);
        setActivePreset(null);
    }, [setWatermarkEnabled, setActivePreset]);

    const jobId = selectedJob?.id;

    // Optimized: Memoize Styles Panel to prevent VDOM re-creation on high-frequency Context updates (like currentTime)
    const stylesPanel = useMemo(() => (
        <div
            role="tabpanel"
            id="panel-styles"
            aria-labelledby="tab-styles"
            className="animate-fade-in pr-2"
        >
            {/* Style Presets Grid */}
            <StylePresetTiles
                presets={STYLE_PRESETS}
                activePreset={activePreset}
                lastUsedSettings={lastUsedSettings}
                onSelectPreset={handlePresetSelect}
                onSelectLastUsed={handleLastUsedSelect}
            />

            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] mb-3">{t('customSettings')}</h4>
            <SubtitlePositionSelector
                value={subtitlePosition}
                onChange={handlePositionChange}
                lines={maxSubtitleLines}
                onChangeLines={handleLinesChange}
                subtitleColor={subtitleColor}
                onChangeColor={handleColorChange}
                colors={SUBTITLE_COLORS}
                subtitleSize={subtitleSize}
                onChangeSize={handleSizeChange}
                karaokeEnabled={karaokeEnabled}
                onChangeKaraoke={handleKaraokeChange}
                watermarkEnabled={watermarkEnabled}
                onChangeWatermark={handleWatermarkChange}
            />
        </div>
    ), [
        activePreset,
        lastUsedSettings,
        STYLE_PRESETS,
        subtitlePosition,
        maxSubtitleLines,
        subtitleColor,
        SUBTITLE_COLORS,
        subtitleSize,
        karaokeEnabled,
        watermarkEnabled,
        handlePresetSelect,
        handleLastUsedSelect,
        handlePositionChange,
        handleLinesChange,
        handleColorChange,
        handleSizeChange,
        handleKaraokeChange,
        handleWatermarkChange,
        t,
    ]);

    // Optimized: Memoize Intelligence Panel
    const intelligencePanel = useMemo(() => (
        <div
            role="tabpanel"
            id="panel-intelligence"
            aria-labelledby="tab-intelligence"
            className="animate-fade-in pr-2"
        >
            {jobId && <ViralIntelligence jobId={jobId} />}
        </div>
    ), [jobId]);

    // Optimized: Memoize the layout to prevent VDOM re-creation during high-frequency ProcessContext updates
    // (e.g. currentTime updating 60fps). Only re-render when relevant state changes.
    return useMemo(() => {
        if (!selectedJob) return null;

        return (
            <aside className="editor-sidebar" data-testid="editor-sidebar">
                {/* Status Header */}
                <div
                    className="editor-sidebar-status"
                    role="status"
                >
                    <div className="editor-sidebar-status-copy">
                        <div
                            className={`editor-sidebar-status-dot ${isProcessing ? 'editor-sidebar-status-dot-processing' : ''}`}
                            aria-label={isProcessing ? (t('statusProcessing') || "Processing") : (t('statusReady') || "Ready")}
                        />
                        <h3 title={selectedJob.result_data?.original_filename || undefined}>
                            {selectedJob.result_data?.original_filename || t('processedVideoFallback')}
                        </h3>
                    </div>
                    {isProcessing && (
                        <span className="editor-sidebar-progress" aria-label={t('progressCompleteLabel', { progress })}>{progress}%</span>
                    )}
                </div>

                <div className="editor-sidebar-body custom-scrollbar">

                    <div
                        role="tablist"
                        className="editor-tabs"
                    >
                        <button
                            role="tab"
                            id="tab-transcript"
                            aria-selected={activeSidebarTab === 'transcript'}
                            aria-controls="panel-transcript"
                            onClick={() => setActiveSidebarTab('transcript')}
                            className={`editor-tab ${activeSidebarTab === 'transcript' ? 'editor-tab-active' : ''}`}
                        >
                            <svg className="hidden h-4 w-4 shrink-0 sm:block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                            <span className="truncate">{t('tabTranscript') || 'Transcript'}</span>
                        </button>
                        <button
                            role="tab"
                            id="tab-styles"
                            aria-selected={activeSidebarTab === 'styles'}
                            aria-controls="panel-styles"
                            onClick={() => setActiveSidebarTab('styles')}
                            className={`editor-tab ${activeSidebarTab === 'styles' ? 'editor-tab-active' : ''}`}
                        >
                            <svg className="hidden h-4 w-4 shrink-0 sm:block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
                            </svg>
                            <span className="truncate">{t('tabStyles') || 'Styles'}</span>
                        </button>
                        <button
                            role="tab"
                            id="tab-intelligence"
                            aria-selected={activeSidebarTab === 'intelligence'}
                            aria-controls="panel-intelligence"
                            onClick={() => setActiveSidebarTab('intelligence')}
                            className={`editor-tab ${activeSidebarTab === 'intelligence' ? 'editor-tab-active' : ''}`}
                        >
                            <svg className="hidden h-4 w-4 shrink-0 sm:block" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M9.5 2A5.5 5.5 0 0 0 4 7.5c0 1.63.71 3.1 1.84 4.1A4.5 4.5 0 0 0 5 16.5 4.5 4.5 0 0 0 9.5 21h5a4.5 4.5 0 0 0 4.5-4.5 4.5 4.5 0 0 0-.84-2.6A5.5 5.5 0 0 0 20 7.5a5.5 5.5 0 0 0-5.5-5.5h-5z" />
                                <path d="M12 2v19" />
                                <path d="M8 7c0 .5-.5 1-1 1s-1-.5-1-1 1-2 2-2 2 1.5 2 2" />
                                <path d="M16 7c0 .5.5 1 1 1s1-.5 1-1-1-2-2-2-2 1.5-2 2" />
                                <path d="M9 14c0 .5-.5 1-1 1s-1-.5-1-1 1-2 2-2" />
                                <path d="M15 14c0 .5.5 1 1 1s1-.5 1-1-1-2-2-2" />
                            </svg>
                            <span className="truncate">{t('tabIntelligence') || 'Intelligence'}</span>
                        </button>
                    </div>

                    {/* Tab Content */}
                    <div className="editor-tab-content">
                        {activeSidebarTab === 'transcript' && (
                            <TranscriptPanel />
                        )}

                        {activeSidebarTab === 'styles' && stylesPanel}

                        {activeSidebarTab === 'intelligence' && intelligencePanel}
                    </div>
                </div>
            </aside>
        );
    }, [
        selectedJob,
        isProcessing,
        progress,
        activeSidebarTab,
        setActiveSidebarTab,
        t,
        stylesPanel,
        intelligencePanel
    ]);
}
