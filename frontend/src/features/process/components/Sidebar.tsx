import React, { useCallback, useEffect, useMemo, memo } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { CueItem } from '../CueItem';
import { Cue } from '@/components/SubtitleOverlay';
import { findCueIndexAtTime } from '@/lib/subtitleUtils';
import { SubtitlePositionSelector } from '@/components/SubtitlePositionSelector';
import { ViralIntelligence } from '@/components/ViralIntelligence';
import { StylePresetTiles, StylePreset } from './StylePresetTiles';

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
    onUpdateDraft
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
        currentTime,
        editingCueIndex,
        editingCueDraft,
        isSavingTranscript,
        transcriptSaveError,
        transcriptContainerRef,
        playerRef,
        handleUpdateDraft,
        beginEditingCue,
        saveEditingCue,
        cancelEditingCue
    } = useProcessContext();

    const handleSeek = useCallback((time: number) => {
        playerRef.current?.seekTo(time);
    }, [playerRef]);

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

    return (
        <div
            role="tabpanel"
            id="panel-transcript"
            aria-labelledby="tab-transcript"
            className="space-y-2"
        >
            {transcriptSaveError && (
                <div className="rounded-lg border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-3 py-2 text-xs text-[var(--danger)]">
                    {transcriptSaveError}
                </div>
            )}
            {isSavingTranscript && (
                <div className="flex items-center gap-2 px-1 text-xs text-[var(--muted)]">
                    <span className="animate-spin">⏳</span>
                    {t('transcriptSaving') || 'Saving…'}
                </div>
            )}

            {/* Scrollable Transcript List */}
            <div
                ref={transcriptContainerRef}
                className="max-h-[50vh] overflow-y-auto custom-scrollbar pr-2 space-y-1 scroll-smooth"
                style={{ scrollBehavior: 'smooth' }}
            >
                <CueList
                    cues={cues}
                    activeCueIndex={activeCueIndex}
                    editingCueIndex={editingCueIndex}
                    editingCueDraft={editingCueDraft}
                    isSaving={isSavingTranscript}
                    onSeek={handleSeek}
                    onEdit={beginEditingCue}
                    onSave={saveEditingCue}
                    onCancel={cancelEditingCue}
                    onUpdateDraft={handleUpdateDraft}
                />
                {cues.length === 0 && (
                    <div className="text-center text-[var(--muted)] py-10 opacity-50">
                        {t('liveOutputStatusIdle') || 'Transcript will appear here...'}
                    </div>
                )}
            </div>
        </div>
    );
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
        cues,
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
        videoInfo,
        subtitleColor,
        SUBTITLE_COLORS,
        subtitleSize,
        karaokeEnabled,
        watermarkEnabled,
        setWatermarkEnabled,
        AVAILABLE_MODELS,
        transcribeProvider,
        transcribeMode,
        previewVideoUrl
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
    }, [lastUsedSettings, setActivePreset, setSubtitlePosition, setSubtitleSize, setMaxSubtitleLines, setSubtitleColor, setKaraokeEnabled]);

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

    // Optimized: Calculate derived values outside render loop
    const karaokeSupported = useMemo(() => {
        return AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode)?.stats.karaoke || false;
    }, [AVAILABLE_MODELS, transcribeProvider, transcribeMode]);

    const jobId = selectedJob?.id;
    const thumbnailUrl = videoInfo?.thumbnailUrl;

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

            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] mb-3">Custom Settings</h4>
            <SubtitlePositionSelector
                value={subtitlePosition}
                onChange={handlePositionChange}
                lines={maxSubtitleLines}
                onChangeLines={handleLinesChange}
                thumbnailUrl={thumbnailUrl}
                subtitleColor={subtitleColor}
                onChangeColor={handleColorChange}
                colors={SUBTITLE_COLORS}
                disableMaxLines={transcribeProvider === 'whispercpp'}
                subtitleSize={subtitleSize}
                onChangeSize={handleSizeChange}
                karaokeEnabled={karaokeEnabled}
                onChangeKaraoke={handleKaraokeChange}
                watermarkEnabled={watermarkEnabled}
                onChangeWatermark={handleWatermarkChange}
                karaokeSupported={karaokeSupported}
                previewVideoUrl={previewVideoUrl || undefined}
                cues={cues}
                hidePreview={true}
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
        karaokeSupported,
        transcribeProvider,
        thumbnailUrl,
        previewVideoUrl,
        cues,
        handlePresetSelect,
        handleLastUsedSelect,
        handlePositionChange,
        handleLinesChange,
        handleColorChange,
        handleSizeChange,
        handleKaraokeChange,
        handleWatermarkChange
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

    // Optimized: Wrap entire return in useMemo to prevent unnecessary re-renders
    // caused by high-frequency Context updates (like currentTime) that this component doesn't use.
    const content = useMemo(() => {
        if (!selectedJob) return null;

        return (
            <div className="w-full md:w-[500px] lg:w-[600px] flex flex-col bg-[var(--surface)] border border-[var(--border)] rounded-xl shadow-xl overflow-hidden transition-all duration-500">
                {/* Status Header */}
                <div
                    className="p-4 border-b border-[var(--border)] flex items-center justify-between bg-[var(--surface-elevated)]"
                    role="status"
            >
                <div className="flex items-center gap-3 overflow-hidden">
                    <div
                        className={`w-2.5 h-2.5 rounded-full shrink-0 animate-pulse ${isProcessing ? 'bg-amber-400' : 'bg-emerald-400'}`}
                        aria-label={isProcessing ? (t('statusProcessing') || "Processing") : (t('statusReady') || "Ready")}
                    />
                    <h3 className="font-semibold text-[var(--foreground)] truncate" title={selectedJob.result_data?.original_filename || undefined}>
                        {selectedJob.result_data?.original_filename || t('processedVideoFallback')}
                    </h3>
                </div>
                {isProcessing && (
                    <span className="text-xs font-mono text-amber-400" aria-label={`${progress}% complete`}>{progress}%</span>
                )}
            </div>

            <div className="p-4 sm:p-6 flex-1 flex flex-col min-h-0 custom-scrollbar relative lg:overflow-y-auto">

                <div
                    role="tablist"
                    className="flex items-center gap-1 p-1 bg-[var(--surface-elevated)] rounded-lg border border-[var(--border)] mb-4"
                >
                    <button
                        role="tab"
                        id="tab-transcript"
                        aria-selected={activeSidebarTab === 'transcript'}
                        aria-controls="panel-transcript"
                        onClick={() => setActiveSidebarTab('transcript')}
                        className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-xs font-medium transition-all ${activeSidebarTab === 'transcript'
                            ? 'bg-[var(--accent)] text-[#031018] shadow-sm'
                            : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/5'
                            }`}
                    >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        {t('tabTranscript') || 'Transcript'}
                    </button>
                    <button
                        role="tab"
                        id="tab-styles"
                        aria-selected={activeSidebarTab === 'styles'}
                        aria-controls="panel-styles"
                        onClick={() => setActiveSidebarTab('styles')}
                        className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-xs font-medium transition-all ${activeSidebarTab === 'styles'
                            ? 'bg-[var(--accent)] text-[#031018] shadow-sm'
                            : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/5'
                            }`}
                    >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
                        </svg>
                        {t('tabStyles') || 'Styles'}
                    </button>
                    <button
                        role="tab"
                        id="tab-intelligence"
                        aria-selected={activeSidebarTab === 'intelligence'}
                        aria-controls="panel-intelligence"
                        onClick={() => setActiveSidebarTab('intelligence')}
                        className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-xs font-medium transition-all ${activeSidebarTab === 'intelligence'
                            ? 'bg-[var(--accent)] text-[#031018] shadow-sm'
                            : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/5'
                            }`}
                    >
                        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M9.5 2A5.5 5.5 0 0 0 4 7.5c0 1.63.71 3.1 1.84 4.1A4.5 4.5 0 0 0 5 16.5 4.5 4.5 0 0 0 9.5 21h5a4.5 4.5 0 0 0 4.5-4.5 4.5 4.5 0 0 0-.84-2.6A5.5 5.5 0 0 0 20 7.5a5.5 5.5 0 0 0-5.5-5.5h-5z" />
                            <path d="M12 2v19" />
                            <path d="M8 7c0 .5-.5 1-1 1s-1-.5-1-1 1-2 2-2 2 1.5 2 2" />
                            <path d="M16 7c0 .5.5 1 1 1s1-.5 1-1-1-2-2-2-2 1.5-2 2" />
                            <path d="M9 14c0 .5-.5 1-1 1s-1-.5-1-1 1-2 2-2" />
                            <path d="M15 14c0 .5.5 1 1 1s1-.5 1-1-1-2-2-2" />
                        </svg>
                        {t('tabIntelligence') || 'Intelligence'}
                    </button>
                </div>

                {/* Tab Content */}
                <div className="pr-1">
                    {activeSidebarTab === 'transcript' && (
                        <TranscriptPanel />
                    )}

                    {activeSidebarTab === 'styles' && stylesPanel}

                    {activeSidebarTab === 'intelligence' && intelligencePanel}
                </div>

                <div className="pt-4 mt-4 border-t border-[var(--border)]/60 space-y-4">
                    <div className="flex flex-wrap gap-3">
                        {/* Export buttons moved to PreviewSection */}
                    </div>
                </div>
            </div>
        </div>
        );
    }, [
        selectedJob,
        isProcessing,
        progress,
        activeSidebarTab,
        setActiveSidebarTab,
        stylesPanel,
        intelligencePanel,
        t
    ]);

    return content;
}
