import React from "react";
import type { Cue } from "@/components/SubtitleOverlay";
import { useI18n } from "@/context/I18nContext";

interface CuePositionResetButtonProps {
  index: number;
  canEdit: boolean;
  onReset?: (index: number) => void;
  position?: number | null;
}

function CuePositionResetButton(props: CuePositionResetButtonProps) {
  const { t } = useI18n();
  if (
    props.position === undefined ||
    props.position === null ||
    !props.onReset
  ) {
    return null;
  }
  return (
    <button
      type="button"
      onClick={() => props.onReset?.(props.index)}
      disabled={!props.canEdit}
      className="min-h-11 rounded-md border border-cyan-400/25 bg-cyan-400/10 px-2 text-[10px] font-semibold text-cyan-100 transition-colors hover:bg-cyan-400/15 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      aria-label={t("subtitleResetPosition")}
      title={t("subtitleResetPosition")}
    >
      {t("subtitleResetPositionShort")}
    </button>
  );
}

interface CueItemReadActionsProps {
  cue: Cue;
  index: number;
  canEdit: boolean;
  formattedTime: string;
  editButtonRef: React.RefObject<HTMLButtonElement | null>;
  onEdit: (index: number) => void;
  onResetPosition?: (index: number) => void;
}

export function CueItemReadActions({
  cue,
  index,
  canEdit,
  formattedTime,
  editButtonRef,
  onEdit,
  onResetPosition,
}: CueItemReadActionsProps) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">
      <CuePositionResetButton
        index={index}
        canEdit={canEdit}
        onReset={onResetPosition}
        position={cue.position}
      />
      <button
        ref={editButtonRef}
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
  );
}
