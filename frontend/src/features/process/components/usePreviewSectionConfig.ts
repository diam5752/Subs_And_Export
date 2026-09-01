import { useMemo, useState } from "react";
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
  scope: SubtitlePositionScope;
  disabled: boolean;
  onScopeChange: (scope: SubtitlePositionScope) => void;
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
  scope: SubtitlePositionScope,
  t: Translate,
  actions: SubtitlePositionActions,
): SubtitleTransformConfig {
  return {
    labels: {
      move: t(
        scope === "cue"
          ? "subtitleDragHandleLabel"
          : "subtitleDragAllHandleLabel",
      ),
      resize: t("subtitleResizeHandleLabel"),
      customPosition: t("subtitleCustomPosition"),
      sharedPosition: t("subtitleSharedPosition"),
    },
    onPositionChange: (sourceCueIndex, position) => {
      actions.change(sourceCueIndex, position, scope);
    },
    onPositionCommit: (sourceCueIndex) => {
      void actions.commit(sourceCueIndex, scope);
    },
    onPositionCancel: (sourceCueIndex) => {
      actions.cancel(sourceCueIndex, scope);
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
  const [scope, setScope] = useState<SubtitlePositionScope>("cue");
  const transformControls = useMemo<SubtitleTransformConfig | undefined>(
    () =>
      isSavingTranscript
        ? undefined
        : buildSubtitleTransformControls(scope, t, {
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
      scope,
      t,
    ],
  );
  return {
    scope,
    disabled: isSavingTranscript,
    onScopeChange: setScope,
    transformControls,
  };
}
