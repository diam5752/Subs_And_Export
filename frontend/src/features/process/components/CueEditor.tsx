import React from "react";
import { Spinner } from "@/components/Spinner";
import { useI18n } from "@/context/I18nContext";

type Translate = ReturnType<typeof useI18n>["t"];

interface CueEditActionsProps {
  isSaving: boolean;
  t: Translate;
  onSave: () => void;
  onCancel: () => void;
}

function CueEditActions(props: CueEditActionsProps) {
  return (
    <div className="flex items-center justify-end gap-2">
      <span className="text-[10px] text-[var(--muted)] hidden sm:inline-block mr-2 opacity-70">
        {props.t("transcriptEditHint") || "Ctrl+Enter to save"}
      </span>
      <button
        type="button"
        onClick={props.onCancel}
        disabled={props.isSaving}
        className="cue-form-action px-2.5 py-1.5 rounded-md text-xs font-medium bg-white/5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 border border-white/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        title={`${props.t("transcriptCancel") || "Cancel"} (Esc)`}
        aria-label={props.t("transcriptCancel") || "Cancel editing"}
      >
        {props.t("transcriptCancel") || "Cancel"}
      </button>
      <button
        type="button"
        onClick={props.onSave}
        disabled={props.isSaving}
        className="cue-form-action px-2.5 py-1.5 rounded-md text-xs font-semibold bg-emerald-500/15 text-emerald-200 border border-emerald-500/25 hover:bg-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
        title={`${props.t("transcriptSave") || "Save"} (Ctrl+Enter)`}
        aria-label={props.t("transcriptSave") || "Save changes"}
        aria-busy={props.isSaving}
      >
        {props.isSaving ? (
          <>
            <Spinner className="w-3.5 h-3.5 text-emerald-200" />
            <span>{props.t("transcriptSaving") || "Saving…"}</span>
          </>
        ) : (
          <>
            <span>{props.t("transcriptSave") || "Save"}</span>
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

export function CueEditor({
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
