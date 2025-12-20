import React, { memo, useRef, useEffect } from 'react';
import { Cue } from '@/components/SubtitleOverlay';
import { useI18n } from '@/context/I18nContext';

interface CueItemProps {
    cue: Cue;
    index: number;
    isActive: boolean;
    isEditing: boolean;
    canEdit: boolean;
    draftText: string;
    isSaving: boolean;
    onSeek: (time: number) => void;
    onEdit: (index: number) => void;
    onSave: () => void;
    onCancel: () => void;
    onUpdateDraft: (text: string) => void;
}

export const CueItem = memo(({
    cue,
    index,
    isActive,
    isEditing,
    canEdit,
    draftText,
    isSaving,
    onSeek,
    onEdit,
    onSave,
    onCancel,
    onUpdateDraft
}: CueItemProps) => {
    const { t } = useI18n();
    const formattedTime = `${Math.floor(cue.start / 60)}:${(cue.start % 60).toFixed(0).padStart(2, '0')}`;

    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const editBtnRef = useRef<HTMLButtonElement>(null);
    const prevIsEditingRef = useRef(isEditing);
    const shouldRestoreFocusRef = useRef(false);

    useEffect(() => {
        // Entering edit mode
        if (isEditing && !prevIsEditingRef.current) {
            requestAnimationFrame(() => {
                textareaRef.current?.focus();
            });
        }

        // Exiting edit mode
        if (!isEditing && prevIsEditingRef.current) {
            if (shouldRestoreFocusRef.current) {
                requestAnimationFrame(() => {
                    editBtnRef.current?.focus();
                });
                shouldRestoreFocusRef.current = false;
            }
        }

        prevIsEditingRef.current = isEditing;
    }, [isEditing]);

    const handleSave = () => {
        shouldRestoreFocusRef.current = true;
        onSave();
    };

    const handleCancel = () => {
        shouldRestoreFocusRef.current = true;
        onCancel();
    };

    return (
        <div
            id={`cue-${index}`}
            className={`rounded-lg border px-2 py-2 transition-colors ${isActive
                ? 'border-[var(--accent)]/25 bg-[var(--accent)]/10'
                : 'border-transparent hover:bg-white/5'
                }`}
        >
            <div className="flex items-start gap-3">
                <button
                    type="button"
                    onClick={() => onSeek(cue.start)}
                    className="font-mono text-xs opacity-60 pt-0.5 min-w-[42px] text-left hover:opacity-90 transition-opacity"
                    aria-label={t('jumpToTime')?.replace('{time}', formattedTime) || `Jump to ${formattedTime}`}
                >
                    {formattedTime}
                </button>
                <div className="flex-1 min-w-0">
                    {isEditing ? (
                        <textarea
                            ref={textareaRef}
                            value={draftText}
                            onChange={(e) => onUpdateDraft(e.target.value)}
                            className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]/70 px-3 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 min-h-[72px] resize-y"
                            disabled={isSaving}
                            aria-label={t('transcriptEdit') || 'Edit'}
                        />
                    ) : (
                        <button
                            type="button"
                            onClick={() => onSeek(cue.start)}
                            className={`w-full text-left text-sm break-words [overflow-wrap:anywhere] ${isActive
                                ? 'text-[var(--foreground)] font-medium'
                                : 'text-[var(--muted)] hover:text-[var(--foreground)]'
                                }`}
                            aria-label={t('jumpToCue')?.replace('{text}', cue.text) || `Jump to cue: ${cue.text}`}
                        >
                            {cue.text}
                        </button>
                    )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">
                    {isEditing ? (
                        <>
                            <button
                                type="button"
                                onClick={handleSave}
                                disabled={isSaving}
                                className="px-2 py-1 rounded-md text-xs font-semibold bg-emerald-500/15 text-emerald-200 border border-emerald-500/25 hover:bg-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {isSaving ? (t('transcriptSaving') || 'Saving…') : (t('transcriptSave') || 'Save')}
                            </button>
                            <button
                                type="button"
                                onClick={handleCancel}
                                disabled={isSaving}
                                className="px-2 py-1 rounded-md text-xs font-medium bg-white/5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 border border-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {t('transcriptCancel') || 'Cancel'}
                            </button>
                        </>
                    ) : (
                        <button
                            ref={editBtnRef}
                            type="button"
                            onClick={() => onEdit(index)}
                            disabled={!canEdit}
                            className="px-2 py-1 rounded-md text-xs font-medium bg-white/5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 border border-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            {t('transcriptEdit') || 'Edit'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
});

CueItem.displayName = 'CueItem';
