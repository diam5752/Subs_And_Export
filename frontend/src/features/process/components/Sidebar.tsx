import React, { useCallback, useEffect, useMemo, memo, useRef } from 'react';
import dynamic from 'next/dynamic';
import { Spinner } from '@/components/Spinner';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { usePlaybackContext } from '../PlaybackContext';
import { CueItem } from '../CueItem';
import { Cue } from '@/components/SubtitleOverlay';
import { findCueIndexAtTime } from '@/lib/subtitleUtils';

const SubtitlePositionSelector = dynamic(() => (
    import('@/components/SubtitlePositionSelector').then((module) => module.SubtitlePositionSelector)
));

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
                    <CueItem
                        key={`${cue.start}-${cue.end}-${index}`}
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
        activeSidebarTab,
        setActiveSidebarTab,
        setSubtitleSize,
        setMaxSubtitleLines,
        setSubtitleColor,
        maxSubtitleLines,
        subtitleColor,
        SUBTITLE_COLORS,
        subtitleSize,
    } = useProcessContext();

    const sidebarBodyRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (sidebarBodyRef.current) {
            sidebarBodyRef.current.scrollTop = 0;
        }
    }, [activeSidebarTab]);

    const handleSidebarTabChange = useCallback((
        tab: 'transcript' | 'styles',
    ) => {
        setActiveSidebarTab(tab);

        if (
            tab !== 'styles'
            || typeof window === 'undefined'
            || !window.matchMedia?.('(max-width: 899px)').matches
        ) {
            return;
        }

        window.requestAnimationFrame(() => {
            // Keep the completed-job actions in the scroll target. Scrolling
            // the workspace itself placed the preceding New Video / Export
            // row underneath the fixed mobile header.
            const previewSection = document.getElementById('preview-section');
            const reduceMotion = window.matchMedia?.(
                '(prefers-reduced-motion: reduce)',
            ).matches;
            previewSection?.scrollIntoView?.({
                behavior: reduceMotion ? 'auto' : 'smooth',
                block: 'start',
            });
        });
    }, [setActiveSidebarTab]);

    // Optimized: Memoize Styles Panel to prevent VDOM re-creation on high-frequency Context updates (like currentTime)
    const stylesPanel = useMemo(() => (
        <div
            role="tabpanel"
            id="panel-styles"
            aria-labelledby="tab-styles"
            className="editor-style-panel animate-fade-in pr-2"
            data-testid="editor-style-panel"
        >
            <SubtitlePositionSelector
                lines={maxSubtitleLines}
                onChangeLines={setMaxSubtitleLines}
                subtitleColor={subtitleColor}
                onChangeColor={setSubtitleColor}
                colors={SUBTITLE_COLORS}
                subtitleSize={subtitleSize}
                onChangeSize={setSubtitleSize}
            />
        </div>
    ), [
        maxSubtitleLines,
        subtitleColor,
        SUBTITLE_COLORS,
        subtitleSize,
        setMaxSubtitleLines,
        setSubtitleColor,
        setSubtitleSize,
    ]);

    // Optimized: Memoize the layout to prevent VDOM re-creation during high-frequency ProcessContext updates
    // (e.g. currentTime updating 60fps). Only re-render when relevant state changes.
    return useMemo(() => {
        if (!selectedJob) return null;

        return (
            <aside className="editor-sidebar" data-testid="editor-sidebar">
                <div ref={sidebarBodyRef} className="editor-sidebar-body custom-scrollbar">
                    <div className="editor-tabs-sticky">
                    <div
                        role="tablist"
                        className="editor-tabs editor-tabs-two"
                    >
                        <button
                            role="tab"
                            id="tab-transcript"
                            aria-label={t('tabTranscript') || 'Transcript'}
                            aria-selected={activeSidebarTab === 'transcript'}
                            aria-controls="panel-transcript"
                            onClick={() => handleSidebarTabChange('transcript')}
                            className={`editor-tab ${activeSidebarTab === 'transcript' ? 'editor-tab-active' : ''}`}
                        >
                            <svg className="hidden h-4 w-4 shrink-0 sm:block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                            <span className="editor-tab-label-full truncate">
                                {t('tabTranscript') || 'Transcript'}
                            </span>
                            <span className="editor-tab-label-short">
                                {t('stepCaptions') || 'Captions'}
                            </span>
                        </button>
                        <button
                            role="tab"
                            id="tab-styles"
                            aria-selected={activeSidebarTab === 'styles'}
                            aria-controls="panel-styles"
                            onClick={() => handleSidebarTabChange('styles')}
                            className={`editor-tab ${activeSidebarTab === 'styles' ? 'editor-tab-active' : ''}`}
                        >
                            <svg className="hidden h-4 w-4 shrink-0 sm:block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
                            </svg>
                            <span className="truncate">{t('tabStyles') || 'Styles'}</span>
                        </button>
                    </div>
                    </div>

                    {/* Tab Content */}
                    <div className="editor-tab-content">
                        {activeSidebarTab === 'transcript' && (
                            <TranscriptPanel />
                        )}

                        {activeSidebarTab === 'styles' && stylesPanel}
                    </div>
                </div>
            </aside>
        );
    }, [
        selectedJob,
        activeSidebarTab,
        handleSidebarTabChange,
        t,
        stylesPanel,
    ]);
}
