import { useMemo } from "react";
import type {
  InlineSubtitleEditorConfig,
  SubtitleTransformConfig,
} from "@/components/PreviewPlayer";
import type { SubtitlePositionScope } from "@/components/SubtitleOverlay";
import { useI18n } from "@/context/I18nContext";
import { useProcessContext } from "../ProcessContext";

export function usePreviewPlayerSettings() {
  const process = useProcessContext();
  return useMemo(
    () => ({
      position: process.subtitlePosition,
      color: process.subtitleColor,
      fontSize: process.subtitleSize,
      karaoke: process.karaokeEnabled,
      maxLines: process.maxSubtitleLines,
      shadowStrength: process.shadowStrength,
      watermarkEnabled: process.watermarkEnabled,
    }),
    [
      process.subtitlePosition,
      process.subtitleColor,
      process.subtitleSize,
      process.karaokeEnabled,
      process.maxSubtitleLines,
      process.shadowStrength,
      process.watermarkEnabled,
    ],
  );
}

export function usePreviewSubtitleEditor(): InlineSubtitleEditorConfig {
  const { t } = useI18n();
  const process = useProcessContext();
  return useMemo(
    () => ({
      cues: process.cues,
      editingCueIndex: process.editingCueIndex,
      draftText: process.editingCueDraft,
      isSaving: process.isSavingTranscript,
      error: process.transcriptSaveError,
      autoFocus: process.editingCueSurface === "video",
      labels: {
        editAction: t("subtitleInlineEditAction"),
        title: t("subtitleInlineEditorTitle"),
        textarea: t("subtitleInlineTextareaLabel"),
        save: t("transcriptSave"),
        cancel: t("transcriptCancel"),
        shortcut: t("transcriptEditHint"),
        saving: t("transcriptSaving"),
      },
      onBeginEdit: (index) => process.beginEditingCue(index, "video"),
      onChange: process.handleUpdateDraft,
      onSave: process.saveEditingCue,
      onCancel: process.cancelEditingCue,
    }),
    [process, t],
  );
}

export interface LiveSubtitlePositioning {
  transformControls?: SubtitleTransformConfig;
}

type Translate = ReturnType<typeof useI18n>["t"];

interface SubtitlePositionActions {
  change: (
    sourceCueIndex: number,
    position: number,
    scope: SubtitlePositionScope,
  ) => void;
  commit: (
    sourceCueIndex: number,
    scope: SubtitlePositionScope,
  ) => Promise<void>;
  cancel: (sourceCueIndex: number, scope: SubtitlePositionScope) => void;
  resize: (size: number) => void;
}

function buildSubtitleTransformControls(
  t: Translate,
  actions: SubtitlePositionActions,
): SubtitleTransformConfig {
  return {
    labels: {
      move: t("subtitleDragAllHandleLabel"),
      moveCue: t("subtitleDragHandleLabel"),
      resize: t("subtitleResizeHandleLabel"),
      customPosition: t("subtitleCustomPosition"),
      sharedPosition: t("subtitleSharedPosition"),
    },
    onPositionChange: (sourceCueIndex, position) => {
      actions.change(sourceCueIndex, position, "all");
    },
    onPositionCommit: (sourceCueIndex) => {
      void actions.commit(sourceCueIndex, "all");
    },
    onPositionCancel: (sourceCueIndex) => {
      actions.cancel(sourceCueIndex, "all");
    },
    onCuePositionChange: (sourceCueIndex, position) => {
      actions.change(sourceCueIndex, position, "cue");
    },
    onCuePositionCommit: (sourceCueIndex) => {
      void actions.commit(sourceCueIndex, "cue");
    },
    onCuePositionCancel: (sourceCueIndex) => {
      actions.cancel(sourceCueIndex, "cue");
    },
    onSizeChange: actions.resize,
  };
}

export function useLiveSubtitlePositioning(): LiveSubtitlePositioning {
  const { t } = useI18n();
  const {
    cancelCuePosition,
    changeCuePosition,
    commitCuePosition,
    isSavingTranscript,
    setSubtitleSize,
  } = useProcessContext();
  const transformControls = useMemo<SubtitleTransformConfig | undefined>(
    () =>
      isSavingTranscript
        ? undefined
        : buildSubtitleTransformControls(t, {
            change: changeCuePosition,
            commit: commitCuePosition,
            cancel: cancelCuePosition,
            resize: setSubtitleSize,
          }),
    [
      cancelCuePosition,
      changeCuePosition,
      commitCuePosition,
      isSavingTranscript,
      setSubtitleSize,
      t,
    ],
  );
  return {
    transformControls,
  };
}
