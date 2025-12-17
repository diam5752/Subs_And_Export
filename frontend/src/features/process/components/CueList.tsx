import React, { memo } from 'react';
import { Cue } from '@/components/SubtitleOverlay';
import { CueItem } from '../CueItem';
import { useI18n } from '@/context/I18nContext';

interface CueListProps {
    cues: Cue[];
    activeCueIndex: number;
    editingCueIndex: number | null;
    editingCueDraft: string;
    isSavingTranscript: boolean;
    transcriptContainerRef: React.RefObject<HTMLDivElement | null>;
    onSeek: (time: number) => void;
    onBeginEditing: (index: number) => void;
    onSaveEditing: () => void;
    onCancelEditing: () => void;
    onUpdateDraft: (text: string) => void;
}

export const CueList = memo(function CueList({
    cues,
    activeCueIndex,
    editingCueIndex,
    editingCueDraft,
    isSavingTranscript,
    transcriptContainerRef,
    onSeek,
    onBeginEditing,
    onSaveEditing,
    onCancelEditing,
    onUpdateDraft,
}: CueListProps) {
    const { t } = useI18n();

    return (
        <div
            ref={transcriptContainerRef}
            className="max-h-[50vh] overflow-y-auto custom-scrollbar pr-2 space-y-1 scroll-smooth"
            style={{ scrollBehavior: 'smooth' }}
        >
            {cues.map((cue, index) => {
                const isActive = index === activeCueIndex;
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
                            onSeek={onSeek}
                            onEdit={onBeginEditing}
                            onSave={onSaveEditing}
                            onCancel={onCancelEditing}
                            onUpdateDraft={onUpdateDraft}
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
    );
});
