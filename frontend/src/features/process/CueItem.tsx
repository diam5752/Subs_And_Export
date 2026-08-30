import React, { memo, useRef, useEffect } from "react";
import { Cue } from "@/components/SubtitleOverlay";
import { useI18n } from "@/context/I18nContext";
import { Spinner } from "@/components/Spinner";

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
  autoFocusEditor?: boolean;
}

type Translate = ReturnType<typeof useI18n>["t"];

interface CueEditActionsProps {
  isSaving: boolean;
  t: Translate;
  onSave: () => void;
  onCancel: () => void;
}

function CueEditActions({
  isSaving,
  t,
  onSave,
  onCancel,
}: CueEditActionsProps) {
  return (
    <div className="flex items-center justify-end gap-2">
      <span className="text-[10px] text-[var(--muted)] hidden sm:inline-block mr-2 opacity-70">
        {t("transcriptEditHint") || "Ctrl+Enter to save"}
      </span>
      <button
        type="button"
        onClick={onCancel}
        disabled={isSaving}
        className="cue-form-action px-2.5 py-1.5 rounded-md text-xs font-medium bg-white/5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 border border-white/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        title={`${t("transcriptCancel") || "Cancel"} (Esc)`}
        aria-label={t("transcriptCancel") || "Cancel editing"}
      >
        {t("transcriptCancel") || "Cancel"}
      </button>
      <button
        type="button"
        onClick={onSave}
        disabled={isSaving}
        className="cue-form-action px-2.5 py-1.5 rounded-md text-xs font-semibold bg-emerald-500/15 text-emerald-200 border border-emerald-500/25 hover:bg-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
        title={`${t("transcriptSave") || "Save"} (Ctrl+Enter)`}
        aria-label={t("transcriptSave") || "Save changes"}
        aria-busy={isSaving}
      >
        {isSaving ? (
          <>
            <Spinner className="w-3.5 h-3.5 text-emerald-200" />
            <span>{t("transcriptSaving") || "Saving…"}</span>
          </>
        ) : (
          <>
            <span>{t("transcriptSave") || "Save"}</span>
            <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1 rounded bg-emerald-500/20 border border-emerald-500/30 text-[9px] font-sans opacity-80">
              ⌘↵
            </kbd>
          </>
        )}
      </button>
    </div>
  );
}

interface CueEditorProps extends CueEditActionsProps {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  draftText: string;
  onUpdateDraft: (text: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
}

function CueEditor({
  textareaRef,
  draftText,
  isSaving,
  t,
  onUpdateDraft,
  onKeyDown,
  onSave,
  onCancel,
}: CueEditorProps) {
  return (
    <div className="space-y-2">
      <textarea
        ref={textareaRef}
        value={draftText}
        onChange={(event) => onUpdateDraft(event.target.value)}
        onKeyDown={onKeyDown}
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]/70 px-3 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 min-h-[72px] resize-y"
        disabled={isSaving}
        aria-label={t("transcriptEdit") || "Edit transcript"}
        aria-keyshortcuts="Control+Enter Escape"
      />
      <CueEditActions
        isSaving={isSaving}
        t={t}
        onSave={onSave}
        onCancel={onCancel}
      />
    </div>
  );
}

function CueTimeButton({
  start,
  formattedTime,
  t,
  onSeek,
}: {
  start: number;
  formattedTime: string;
  t: Translate;
  onSeek: (time: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSeek(start)}
      className="cue-time-button font-mono text-xs opacity-60 pt-0.5 min-w-[42px] text-left hover:opacity-90 transition-opacity focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none rounded-sm"
      aria-label={
        t("jumpToTime")?.replace("{time}", formattedTime) ||
        `Jump to ${formattedTime}`
      }
    >
      {formattedTime}
    </button>
  );
}

export const CueItem = memo(
  ({
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
    onUpdateDraft,
    autoFocusEditor = true,
  }: CueItemProps) => {
    const { t } = useI18n();
    const formattedTime = `${Math.floor(cue.start / 60)}:${(cue.start % 60).toFixed(0).padStart(2, "0")}`;

    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const editBtnRef = useRef<HTMLButtonElement>(null);
    const prevIsEditingRef = useRef(isEditing);
    const shouldRestoreFocusRef = useRef(false);

    useEffect(() => {
      // Entering edit mode
      if (isEditing && !prevIsEditingRef.current && autoFocusEditor) {
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
    }, [autoFocusEditor, isEditing]);

    const handleSave = () => {
      shouldRestoreFocusRef.current = true;
      onSave();
    };

    const handleCancel = () => {
      shouldRestoreFocusRef.current = true;
      onCancel();
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        handleSave();
      } else if (e.key === "Escape") {
        e.preventDefault();
        handleCancel();
      }
    };

    return (
      <div
        id={`cue-${index}`}
        className={`rounded-lg border px-2 py-2 transition-colors ${
          isActive
            ? "border-[var(--accent)]/25 bg-[var(--accent)]/10"
            : "border-transparent hover:bg-white/5"
        }`}
      >
        <div className="flex items-start gap-3">
          <CueTimeButton
            start={cue.start}
            formattedTime={formattedTime}
            t={t}
            onSeek={onSeek}
          />
          <div className="flex-1 min-w-0">
            {isEditing ? (
              <CueEditor
                textareaRef={textareaRef}
                draftText={draftText}
                isSaving={isSaving}
                t={t}
                onUpdateDraft={onUpdateDraft}
                onKeyDown={handleKeyDown}
                onSave={handleSave}
                onCancel={handleCancel}
              />
            ) : (
              <button
                type="button"
                onClick={() => onSeek(cue.start)}
                className={`cue-text-button w-full text-left text-sm break-words [overflow-wrap:anywhere] rounded-sm focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none p-0.5 -m-0.5 transition-colors ${
                  isActive
                    ? "text-[var(--foreground)] font-medium"
                    : "text-[var(--muted)] hover:text-[var(--foreground)]"
                }`}
                aria-label={
                  t("jumpToCue")?.replace("{text}", cue.text) ||
                  `Jump to cue: ${cue.text}`
                }
              >
                {cue.text}
              </button>
            )}
          </div>
          {!isEditing && (
            <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">
              <button
                ref={editBtnRef}
                type="button"
                onClick={() => onEdit(index)}
                disabled={!canEdit}
                className="cue-edit-button px-2 py-1 rounded-md text-xs font-medium bg-white/5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 border border-white/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none"
                aria-label={
                  t("transcriptEditAtTime", { time: formattedTime }) ||
                  `Edit subtitle at ${formattedTime}`
                }
              >
                {t("transcriptEdit") || "Edit"}
              </button>
            </div>
          )}
        </div>
      </div>
    );
  },
);

CueItem.displayName = "CueItem";
