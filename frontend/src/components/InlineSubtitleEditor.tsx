'use client';

import React, { useEffect, useRef } from 'react';
import { Spinner } from '@/components/Spinner';
import { getSubtitlePositionStyle } from '@/lib/subtitleUtils';

export interface InlineSubtitleEditorLabels {
    title: string;
    textarea: string;
    save: string;
    cancel: string;
    shortcut: string;
    saving: string;
}

interface InlineSubtitleEditorProps {
    cueIndex: number;
    draftText: string;
    isSaving: boolean;
    error?: string | null;
    autoFocus?: boolean;
    position: number;
    videoWidth: number;
    videoHeight: number;
    labels: InlineSubtitleEditorLabels;
    onChange: (text: string) => void;
    onSave: () => void;
    onCancel: () => void;
}

export function InlineSubtitleEditor({
    cueIndex,
    draftText,
    isSaving,
    error,
    autoFocus = true,
    position,
    videoWidth,
    videoHeight,
    labels,
    onChange,
    onSave,
    onCancel,
}: InlineSubtitleEditorProps) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const shortcutId = `inline-subtitle-shortcut-${cueIndex}`;
    const compactVideo = videoHeight < 280;
    const placementClass = compactVideo ? 'top-1/2 -translate-y-1/2' : '';
    const placementStyle = compactVideo ? undefined : getSubtitlePositionStyle(position);
    const textareaSizeClass = compactVideo
        ? 'min-h-[54px] text-sm'
        : `min-h-16 ${videoWidth < 280 ? 'text-sm' : 'text-base'}`;

    useEffect(() => {
        if (!autoFocus) return;

        const frameId = requestAnimationFrame(() => {
            const textarea = textareaRef.current;
            if (!textarea) return;
            textarea.focus({ preventScroll: true });
            textarea.setSelectionRange(textarea.value.length, textarea.value.length);
        });

        return () => cancelAnimationFrame(frameId);
    }, [autoFocus]);

    const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            onCancel();
            return;
        }

        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            if (!isSaving) onSave();
        }
    };

    return (
        <form
            data-testid="inline-subtitle-editor"
            aria-label={labels.title}
            onSubmit={(event) => {
                event.preventDefault();
                if (!isSaving) onSave();
            }}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
            className={`absolute left-[5%] right-[5%] z-40 rounded-2xl border border-white/20 bg-[#111216]/95 p-2.5 text-left text-white shadow-[0_18px_45px_rgba(0,0,0,0.55)] backdrop-blur-md pointer-events-auto sm:p-3 ${placementClass}`}
            style={placementStyle}
        >
            <div className="mb-2 flex items-center justify-between gap-2">
                <span className="truncate text-[10px] font-bold uppercase tracking-[0.14em] text-white/75">
                    {labels.title}
                </span>
                <span id={shortcutId} className="sr-only">
                    {labels.shortcut}
                </span>
            </div>

            <textarea
                ref={textareaRef}
                value={draftText}
                onChange={(event) => onChange(event.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isSaving}
                rows={2}
                aria-label={labels.textarea}
                aria-describedby={shortcutId}
                aria-keyshortcuts="Control+Enter Meta+Enter Escape"
                data-testid="inline-subtitle-textarea"
                className={`block w-full resize-none rounded-xl border border-white/15 bg-black/35 px-3 py-2.5 font-bold leading-snug text-white outline-none transition focus:border-white/35 focus:ring-2 focus:ring-[#1473e6] disabled:cursor-wait disabled:opacity-65 ${textareaSizeClass}`}
            />

            {error && (
                <p role="alert" className="mt-2 rounded-lg border border-red-300/25 bg-red-500/15 px-2.5 py-2 text-[10px] leading-4 text-red-100">
                    {error}
                </p>
            )}

            <div className="mt-2 grid grid-cols-2 gap-2">
                <button
                    type="button"
                    onClick={onCancel}
                    disabled={isSaving}
                    className="min-h-11 rounded-xl border border-white/15 bg-white/5 px-3 text-xs font-semibold text-white transition hover:bg-white/10 disabled:cursor-wait disabled:opacity-50"
                >
                    {labels.cancel}
                </button>
                <button
                    type="submit"
                    disabled={isSaving}
                    aria-busy={isSaving}
                    className="flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#1473e6] px-3 text-xs font-bold text-white transition hover:bg-[#0f66d0] disabled:cursor-wait disabled:opacity-60"
                >
                    {isSaving && <Spinner className="h-3.5 w-3.5" />}
                    <span>{isSaving ? labels.saving : labels.save}</span>
                </button>
            </div>
        </form>
    );
}
