import React, { memo, useCallback, useEffect, useMemo } from "react";
import { Spinner } from "@/components/Spinner";
import type { Cue } from "@/components/SubtitleOverlay";
import { useI18n } from "@/context/I18nContext";
import { findCueIndexAtTime } from "@/lib/subtitleUtils";
import { CueItem } from "../CueItem";
import { usePlaybackContext } from "../PlaybackContext";
import { useProcessContext } from "../ProcessContext";

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
  onResetPosition: (index: number) => void;
}

function CueListEntry({
  cue,
  index,
  props,
}: {
  cue: Cue;
  index: number;
  props: CueListProps;
}) {
  const isEditing = props.editingCueIndex === index;
  return (
    <CueItem
      cue={cue}
      index={index}
      isActive={index === props.activeCueIndex}
      isEditing={isEditing}
      canEdit={!props.isSaving && (props.editingCueIndex === null || isEditing)}
      draftText={isEditing ? props.editingCueDraft : ""}
      isSaving={props.isSaving}
      onSeek={props.onSeek}
      onEdit={props.onEdit}
      onSave={props.onSave}
      onCancel={props.onCancel}
      onUpdateDraft={props.onUpdateDraft}
      autoFocusEditor={props.autoFocusEditor}
      onResetPosition={props.onResetPosition}
    />
  );
}

const CueList = memo((props: CueListProps) => (
  <>
    {props.cues.map((cue, index) => (
      <CueListEntry
        key={`${cue.start}-${cue.end}-${index}`}
        cue={cue}
        index={index}
        props={props}
      />
    ))}
  </>
));
CueList.displayName = "CueList";

interface TranscriptContentProps extends CueListProps {
  transcriptLoadError: string | null;
  transcriptSaveError: string | null;
  savingLabel: string;
  emptyLabel: string;
}

const TranscriptContent = memo(
  React.forwardRef<HTMLDivElement, TranscriptContentProps>((props, ref) => (
    <div
      role="tabpanel"
      id="panel-transcript"
      aria-labelledby="tab-transcript"
      className="space-y-2"
    >
      {props.transcriptLoadError && (
        <div
          role="alert"
          className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800"
        >
          {props.transcriptLoadError}
        </div>
      )}
      {props.transcriptSaveError && (
        <div className="rounded-lg border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-3 py-2 text-xs text-[var(--danger)]">
          {props.transcriptSaveError}
        </div>
      )}
      {props.isSaving && (
        <div className="flex items-center gap-2 px-1 text-xs text-[var(--muted)]">
          <Spinner className="w-3.5 h-3.5 text-[var(--muted)]" />
          {props.savingLabel}
        </div>
      )}
      <div
        ref={ref}
        className="editor-transcript-list custom-scrollbar scroll-smooth"
      >
        <CueList {...props} />
        {props.cues.length === 0 && (
          <div className="text-center text-[var(--muted)] py-10 opacity-50 font-medium">
            {props.emptyLabel}
          </div>
        )}
      </div>
    </div>
  )),
);
TranscriptContent.displayName = "TranscriptContent";

function seekPlayer(
  playerRef: ReturnType<typeof useProcessContext>["playerRef"],
  time: number,
) {
  playerRef.current?.seekTo(time);
}

function editCue(
  playerRef: ReturnType<typeof useProcessContext>["playerRef"],
  cues: Cue[],
  beginEditingCue: ReturnType<typeof useProcessContext>["beginEditingCue"],
  index: number,
) {
  const cue = cues[index];
  if (!cue) return;
  playerRef.current?.pause();
  playerRef.current?.seekTo(cue.start);
  beginEditingCue(index, "transcript");
}

function useActiveCueScroll(
  activeCueIndex: number,
  editingCueIndex: number | null,
  containerRef: React.RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    if (editingCueIndex !== null || activeCueIndex === -1) return;
    const element = document.getElementById(`cue-${activeCueIndex}`);
    const container = containerRef.current;
    if (!element || !container) return;
    const targetScroll =
      element.offsetTop - container.clientHeight / 2 + element.offsetHeight / 2;
    container.scrollTo({ top: targetScroll, behavior: "smooth" });
  }, [activeCueIndex, editingCueIndex, containerRef]);
}

export const TranscriptPanel = memo(() => {
  const {
    cues,
    playerRef,
    editingCueIndex,
    transcriptContainerRef,
    beginEditingCue,
  } = useProcessContext();
  const { currentTime } = usePlaybackContext();
  const activeCueIndex = useMemo(
    () => (cues.length ? findCueIndexAtTime(cues, currentTime) : -1),
    [cues, currentTime],
  );
  const handleSeek = useCallback(
    (time: number) => seekPlayer(playerRef, time),
    [playerRef],
  );
  const handleEdit = useCallback(
    (index: number) => editCue(playerRef, cues, beginEditingCue, index),
    [beginEditingCue, cues, playerRef],
  );
  useActiveCueScroll(activeCueIndex, editingCueIndex, transcriptContainerRef);
  return (
    <TranscriptPanelView
      activeCueIndex={activeCueIndex}
      onSeek={handleSeek}
      onEdit={handleEdit}
    />
  );
});
TranscriptPanel.displayName = "TranscriptPanel";

function TranscriptPanelView({
  activeCueIndex,
  onSeek,
  onEdit,
}: Pick<CueListProps, "activeCueIndex" | "onSeek" | "onEdit">) {
  const { t } = useI18n();
  const {
    cues,
    editingCueIndex,
    editingCueDraft,
    isSavingTranscript,
    saveEditingCue,
    cancelEditingCue,
    handleUpdateDraft,
    editingCueSurface,
    transcriptContainerRef,
    transcriptLoadError,
    transcriptSaveError,
    isProcessing,
    resetCuePosition,
  } = useProcessContext();
  return (
    <TranscriptContent
      cues={cues}
      activeCueIndex={activeCueIndex}
      editingCueIndex={editingCueIndex}
      editingCueDraft={editingCueDraft}
      isSaving={isSavingTranscript}
      onSeek={onSeek}
      onEdit={onEdit}
      onSave={saveEditingCue}
      onCancel={cancelEditingCue}
      onUpdateDraft={handleUpdateDraft}
      onResetPosition={(index) => {
        void resetCuePosition(index);
      }}
      autoFocusEditor={editingCueSurface !== "video"}
      ref={transcriptContainerRef}
      transcriptLoadError={transcriptLoadError}
      transcriptSaveError={transcriptSaveError}
      savingLabel={t("transcriptSaving") || "Saving…"}
      emptyLabel={
        isProcessing
          ? t("statusProcessing") || "Processing..."
          : t("noSubtitlesFound") || "No subtitles found in this video."
      }
    />
  );
}
