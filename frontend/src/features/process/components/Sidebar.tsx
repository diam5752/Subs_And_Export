import React, { useCallback, useEffect } from 'react';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { CueItem } from '../CueItem';
import { findCueIndexAtTime } from '@/lib/subtitleUtils';
import { SubtitlePositionSelector } from '@/components/SubtitlePositionSelector';
import { ViralIntelligence } from '@/components/ViralIntelligence';

const SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR: Record<string, string> = {
    '#FFFF00': 'bg-[#FFFF00]',
    '#FFFFFF': 'bg-[#FFFFFF]',
    '#00FFFF': 'bg-[#00FFFF]',
    '#00FF00': 'bg-[#00FF00]',
    '#FF00FF': 'bg-[#FF00FF]',
};

function getSubtitlePreviewBgClass(color: string): string {
    const normalized = color.trim().toUpperCase();
    return SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR[normalized] ?? SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR['#FFFF00'];
}

function getPreviewBottomClass(position: number | string): string {
    const numericPosition = typeof position === 'number' ? position : Number(position);

    if (!Number.isNaN(numericPosition)) {
        if (numericPosition >= 40) return 'bottom-[80%]';
        if (numericPosition <= 15) return 'bottom-[20%]';
        return 'bottom-[50%]';
    }

    if (position === 'top') return 'bottom-[80%]';
    if (position === 'bottom') return 'bottom-[20%]';
    return 'bottom-[50%]';
}

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
        previewVideoUrl,
        videoUrl
    } = useProcessContext();

    const handleSeek = useCallback((time: number) => {
        playerRef.current?.seekTo(time);
    }, [playerRef]);

    // Scroll active cue into view
    useEffect(() => {
        if (activeSidebarTab !== 'transcript') return;
        if (editingCueIndex !== null) return;
        if (!cues || cues.length === 0) return;

        const activeIndex = findCueIndexAtTime(cues, currentTime);

        if (activeIndex !== -1 && transcriptContainerRef.current) {
            const element = document.getElementById(`cue-${activeIndex}`);
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
    }, [activeSidebarTab, cues, currentTime, editingCueIndex, transcriptContainerRef]);


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
                <div className="flex items-center gap-1 p-1 bg-[var(--surface-elevated)] rounded-lg border border-[var(--border)] mb-4">
                    <button
                        onClick={() => setActiveSidebarTab('transcript')}
                        className={`flex-1 py-1.5 px-3 rounded-md text-xs font-medium transition-all ${activeSidebarTab === 'transcript'
                            ? 'bg-[var(--accent)] text-[#031018] shadow-sm'
                            : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/5'
                            }`}
                    >
                        {t('tabTranscript') || 'Transcript'}
                    </button>
                    <button
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
                <div className="space-y-2 pr-1">
                    {activeSidebarTab === 'transcript' ? (
                        <>
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
                                {cues.map((cue, index) => {
                                    const isActive = currentTime >= cue.start && currentTime < cue.end;
                                    const isEditing = editingCueIndex === index;
                                    const canEditThis = !isSavingTranscript && (editingCueIndex === null || isEditing);

                                    return (
                                        <div id={`cue-${index}`} key={`${cue.start}-${cue.end}-${index}`}>
                                            <CueItem
                                                cue={cue}
                                                index={index}
                                                isActive={isActive}
                                                isEditing={isEditing}
                                                canEdit={canEditThis}
                                                draftText={isEditing ? editingCueDraft : ''}
                                                isSaving={isSavingTranscript}
                                                onSeek={handleSeek}
                                                onEdit={beginEditingCue}
                                                onSave={saveEditingCue}
                                                onCancel={cancelEditingCue}
                                                onUpdateDraft={handleUpdateDraft}
                                            />
                                        </div>
                                    );
                                })}
                                {cues.length === 0 && (
                                    <div className="text-center text-[var(--muted)] py-10 opacity-50">
                                        {t('liveOutputStatusIdle') || 'Transcript will appear here...'}
                                    </div>
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="animate-fade-in pr-2">
                            {/* Style Presets Grid */}
                            <div
                                className="grid grid-cols-2 gap-3 mb-6"
                                role="radiogroup"
                                aria-label={t('tabStyles') || 'Style Presets'}
                            >
                                {STYLE_PRESETS.map((preset) => {
                                    return (
                                        <button
                                            key={preset.id}
                                            role="radio"
                                            aria-checked={activePreset === preset.id}
                                            aria-label={preset.name}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setActivePreset(preset.id);
                                                setSubtitlePosition(preset.settings.position);
                                                setSubtitleSize(preset.settings.size);
                                                setMaxSubtitleLines(preset.settings.lines);
                                                setSubtitleColor(preset.settings.color);
                                                setKaraokeEnabled(preset.settings.karaoke);
                                            }}
                                            className={`p-3 rounded-xl border text-left transition-all relative overflow-hidden group flex flex-row gap-3 items-center ${activePreset === preset.id
                                                ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]'
                                                : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                } `}
                                        >
                                            <div className={`absolute inset-0 bg-gradient-to-br ${preset.colorClass} opacity-10`} />
                                            <div className="flex-shrink-0 w-10 aspect-[9/16] bg-slate-900 rounded-lg border border-slate-600 overflow-hidden relative shadow-lg">
                                                <div className="absolute top-1 left-1/2 -translate-x-1/2 w-4 h-1 bg-slate-700 rounded-full" />
                                                <div className="absolute inset-0 bg-gradient-to-b from-slate-800/50 to-black/60" />
                                                <div className={`absolute left-1 right-1 flex flex-col gap-[1px] items-center ${getPreviewBottomClass(preset.settings.position)}`}>
                                                    <div className={`h-[2px] w-[75%] rounded-full ${getSubtitlePreviewBgClass(preset.settings.color)}`} />
                                                    {preset.settings.lines > 1 && (
                                                        <div className={`h-[2px] w-[55%] rounded-full ${getSubtitlePreviewBgClass(preset.settings.color)}`} />
                                                    )}
                                                </div>
                                                <div className="absolute bottom-1 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-slate-600 rounded-full" />
                                            </div>
                                            <div className="flex-1 min-w-0 relative">
                                                <div className="flex items-center gap-1.5 mb-0.5">
                                                    <span className="text-sm">{preset.emoji}</span>
                                                    <span className="font-semibold text-xs truncate">{preset.name}</span>
                                                </div>
                                                <p className="text-[10px] text-[var(--muted)] leading-tight line-clamp-2">{preset.description}</p>
                                            </div>
                                            {activePreset === preset.id && (
                                                <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-[var(--accent)] flex items-center justify-center animate-scale-in">
                                                    <svg className="w-2.5 h-2.5 text-[#031018]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                                    </svg>
                                                </div>
                                            )}
                                        </button>
                                    );
                                })}

                                {/* Last Used Tile */}
                                <button
                                    role="radio"
                                    aria-checked={activePreset === 'lastUsed'}
                                    aria-label={t('styleLastUsedName') || 'Last Used'}
                                    aria-disabled={!lastUsedSettings}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        if (!lastUsedSettings) return;
                                        setActivePreset('lastUsed');
                                        setSubtitlePosition(lastUsedSettings.position);
                                        setSubtitleSize(lastUsedSettings.size);
                                        setMaxSubtitleLines(lastUsedSettings.lines);
                                        setSubtitleColor(lastUsedSettings.color);
                                        setKaraokeEnabled(lastUsedSettings.karaoke);
                                    }}
                                    className={`p-3 rounded-xl border text-left transition-all relative overflow-hidden group flex flex-row gap-3 items-center ${activePreset === 'lastUsed'
                                        ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]'
                                        : !lastUsedSettings
                                            ? 'border-[var(--border)] opacity-50 grayscale cursor-not-allowed'
                                            : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                        } `}
                                    disabled={!lastUsedSettings}
                                >
                                    <div className="absolute inset-0 bg-gradient-to-br from-emerald-500 to-teal-600 opacity-10" />
                                    <div className="flex-shrink-0 w-10 aspect-[9/16] bg-slate-900 rounded-lg border border-slate-600 overflow-hidden relative shadow-lg">
                                        <div className="absolute top-1 left-1/2 -translate-x-1/2 w-4 h-1 bg-slate-700 rounded-full" />
                                        <div className="absolute inset-0 bg-gradient-to-b from-slate-800/50 to-black/60" />
                                        {lastUsedSettings ? (
                                            <>
                                                <div className={`absolute left-1 right-1 flex flex-col gap-[1px] items-center ${getPreviewBottomClass(lastUsedSettings.position)}`}>
                                                    <div className={`h-[2px] w-[75%] rounded-full ${getSubtitlePreviewBgClass(lastUsedSettings.color)}`} />
                                                    {lastUsedSettings.lines > 1 && (
                                                        <div className={`h-[2px] w-[55%] rounded-full ${getSubtitlePreviewBgClass(lastUsedSettings.color)}`} />
                                                    )}
                                                </div>
                                            </>
                                        ) : (
                                            <div className="absolute inset-0 flex items-center justify-center">
                                                <svg className="w-4 h-4 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                                </svg>
                                            </div>
                                        )}
                                        <div className="absolute bottom-1 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-slate-600 rounded-full" />
                                    </div>
                                    <div className="flex-1 min-w-0 relative">
                                        <div className="flex items-center gap-1.5 mb-0.5">
                                            <span className="text-sm">🕐</span>
                                            <span className="font-semibold text-xs truncate">{t('styleLastUsedName') || 'Last Used'}</span>
                                        </div>
                                        <p className="text-[10px] text-[var(--muted)] leading-tight line-clamp-2">
                                            {lastUsedSettings ? (t('styleLastUsedDesc') || 'Your most recent settings') : (t('styleLastUsedNoHistory') || 'No previous exports yet')}
                                        </p>
                                    </div>
                                    {activePreset === 'lastUsed' && (
                                        <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-[var(--accent)] flex items-center justify-center animate-scale-in">
                                            <svg className="w-2.5 h-2.5 text-[#031018]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                            </svg>
                                        </div>
                                    )}
                                </button>
                            </div>

                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] mb-3">Custom Settings</h4>
                            <SubtitlePositionSelector
                                value={subtitlePosition}
                                onChange={(v) => { setSubtitlePosition(v); setActivePreset(null); }}
                                lines={maxSubtitleLines}
                                onChangeLines={(v) => { setMaxSubtitleLines(v); setActivePreset(null); }}
                                thumbnailUrl={videoInfo?.thumbnailUrl}
                                subtitleColor={subtitleColor}
                                onChangeColor={(v) => { setSubtitleColor(v); setActivePreset(null); }}
                                colors={SUBTITLE_COLORS}
                                disableMaxLines={transcribeProvider === 'whispercpp'}
                                subtitleSize={subtitleSize}
                                onChangeSize={(v) => { setSubtitleSize(v); setActivePreset(null); }}
                                karaokeEnabled={karaokeEnabled}
                                onChangeKaraoke={(v) => { setKaraokeEnabled(v); setActivePreset(null); }}
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
