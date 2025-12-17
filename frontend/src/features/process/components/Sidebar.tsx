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

export function Sidebar() {
    const { t } = useI18n();
    const {
        selectedJob,
        isProcessing,
        progress,
        transcriptContainerRef,
        activeSidebarTab,
        setActiveSidebarTab,
        transcriptSaveError,
        isSavingTranscript,
        cues,
        currentTime,
        editingCueIndex,
        editingCueDraft,
        handleUpdateDraft,
        beginEditingCue,
        saveEditingCue,
        cancelEditingCue,
        playerRef,
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
        AVAILABLE_MODELS,
        transcribeProvider,
        transcribeMode,
        previewVideoUrl
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
        if (activeSidebarTab !== 'transcript') return;
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
    }, [activeSidebarTab, activeCueIndex, editingCueIndex, transcriptContainerRef]);


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
    const handleKaraokeChange = useCallback((v: boolean) => { setKaraokeEnabled(v); setActivePreset(null); }, [setKaraokeEnabled, setActivePreset]);

    if (!selectedJob) return null;

    return (
        <div className="w-full md:w-[500px] lg:w-[600px] flex flex-col bg-[var(--surface)] border border-[var(--border)] rounded-xl shadow-xl overflow-hidden transition-all duration-500">
            {/* Status Header */}
            <div className="p-4 border-b border-[var(--border)] flex items-center justify-between bg-[var(--surface-elevated)]">
                <div className="flex items-center gap-3 overflow-hidden">
                    <div className={`w-2.5 h-2.5 rounded-full shrink-0 animate-pulse ${isProcessing ? 'bg-amber-400' : 'bg-emerald-400'}`} />
                    <h3 className="font-semibold text-[var(--foreground)] truncate" title={selectedJob.result_data?.original_filename || undefined}>
                        {selectedJob.result_data?.original_filename || t('processedVideoFallback')}
                    </h3>
                </div>
                {isProcessing && (
                    <span className="text-xs font-mono text-amber-400">{progress}%</span>
                )}
            </div>

            <div className="p-4 sm:p-6 flex-1 flex flex-col min-h-0 custom-scrollbar relative lg:overflow-y-auto">

                {/* Sidebar Tabs */}
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
                        className={`flex-1 py-1.5 px-3 rounded-md text-xs font-medium transition-all ${activeSidebarTab === 'transcript'
                            ? 'bg-[var(--accent)] text-[#031018] shadow-sm'
                            : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/5'
                            }`}
                    >
                        {t('tabTranscript') || 'Transcript'}
                    </button>
                    <button
                        role="tab"
                        id="tab-styles"
                        aria-selected={activeSidebarTab === 'styles'}
                        aria-controls="panel-styles"
                        onClick={() => setActiveSidebarTab('styles')}
                        className={`flex-1 py-1.5 px-3 rounded-md text-xs font-medium transition-all ${activeSidebarTab === 'styles'
                            ? 'bg-[var(--accent)] text-[#031018] shadow-sm'
                            : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/5'
                            }`}
                    >
                        {t('tabStyles') || 'Styles'}
                    </button>
                </div>

                {/* Tab Content */}
                <div className="pr-1">
                    {activeSidebarTab === 'transcript' ? (
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
                    ) : (
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
                                thumbnailUrl={videoInfo?.thumbnailUrl}
                                subtitleColor={subtitleColor}
                                onChangeColor={handleColorChange}
                                colors={SUBTITLE_COLORS}
                                disableMaxLines={transcribeProvider === 'whispercpp'}
                                subtitleSize={subtitleSize}
                                onChangeSize={handleSizeChange}
                                karaokeEnabled={karaokeEnabled}
                                onChangeKaraoke={handleKaraokeChange}
                                karaokeSupported={AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode)?.stats.karaoke || false}
                                previewVideoUrl={previewVideoUrl || undefined}
                                cues={cues}
                                hidePreview={true}
                            />
                        </div>
                    )}
                </div>

                <div className="pt-4 mt-4 border-t border-[var(--border)]/60 space-y-4">
                    <div className="flex flex-wrap gap-3">
                        {/* Export buttons moved to PreviewSection */}
                    </div>

                    <ViralIntelligence jobId={selectedJob.id} />
                </div>
            </div>
        </div>
    );
}
