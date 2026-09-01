import type { InlineSubtitleEditorLabels } from "./InlineSubtitleEditor";

export type SubtitlePositionScope = "all" | "cue";

export interface SubtitleTransformControls {
  labels: {
    move: string;
    moveCue?: string;
    resize: string;
    customPosition?: string;
    sharedPosition?: string;
  };
  onPositionChange: (cueIndex: number, position: number) => void;
  onPositionCommit?: (cueIndex: number) => void;
  onPositionCancel?: (cueIndex: number) => void;
  onCuePositionChange?: (cueIndex: number, position: number) => void;
  onCuePositionCommit?: (cueIndex: number) => void;
  onCuePositionCancel?: (cueIndex: number) => void;
  onSizeChange: (size: number) => void;
  onInteractionStart?: () => void;
}

export interface SubtitleOverlayEditorState {
  cueIndex: number;
  isEditing: boolean;
  draftText: string;
  isSaving: boolean;
  error?: string | null;
  autoFocus?: boolean;
  labels: InlineSubtitleEditorLabels & { editAction: string };
  onBeginEdit: () => void;
  onChange: (text: string) => void;
  onSave: () => void;
  onCancel: () => void;
}

export interface SubtitleOverlaySettings {
  position: number;
  color: string;
  fontSize: number;
  karaoke: boolean;
  maxLines: number;
  shadowStrength: number;
}
