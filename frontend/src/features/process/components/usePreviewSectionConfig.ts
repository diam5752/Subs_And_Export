import { useMemo } from "react";
import type {
  InlineSubtitleEditorConfig,
  SubtitleTransformConfig,
} from "@/components/PreviewPlayer";
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

export function usePreviewSubtitleTransforms(): SubtitleTransformConfig {
  const { t } = useI18n();
  const process = useProcessContext();
  return useMemo(
    () => ({
      labels: {
        move: t("subtitleDragHandleLabel"),
        resize: t("subtitleResizeHandleLabel"),
      },
      onPositionChange: process.setSubtitlePosition,
      onSizeChange: process.setSubtitleSize,
    }),
    [process.setSubtitlePosition, process.setSubtitleSize, t],
  );
}
