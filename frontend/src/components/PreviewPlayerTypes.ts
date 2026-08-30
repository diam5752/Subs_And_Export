import type { Cue, SubtitleTransformControls } from "./SubtitleOverlay";
import type { InlineSubtitleEditorLabels } from "./InlineSubtitleEditor";

export interface PreviewPlayerHandle {
  seekTo: (time: number) => void;
  pause: () => void;
  togglePlayback: () => void;
  toggleMuted: () => void;
}

export interface PreviewPlaybackStatus {
  duration: number;
  isPlaying: boolean;
  isMuted: boolean;
}

export interface InlineSubtitleEditorConfig {
  cues: Cue[];
  editingCueIndex: number | null;
  draftText: string;
  isSaving: boolean;
  error?: string | null;
  autoFocus?: boolean;
  labels: InlineSubtitleEditorLabels & { editAction: string };
  onBeginEdit: (index: number) => void;
  onChange: (text: string) => void;
  onSave: () => void;
  onCancel: () => void;
}

export type SubtitleTransformConfig = Omit<
  SubtitleTransformControls,
  "onInteractionStart"
>;

export interface PreviewPlayerProps {
  videoUrl: string;
  cues: Cue[];
  settings: {
    position: number;
    color: string;
    fontSize: number;
    karaoke: boolean;
    maxLines: number;
    shadowStrength: number;
    watermarkEnabled?: boolean;
  };
  onTimeUpdate?: (time: number) => void;
  initialTime?: number;
  subtitleEditor?: InlineSubtitleEditorConfig;
  subtitleTransformControls?: SubtitleTransformConfig;
  playbackToggleLabel?: string;
  onPlaybackStatusChange?: (status: PreviewPlaybackStatus) => void;
}
