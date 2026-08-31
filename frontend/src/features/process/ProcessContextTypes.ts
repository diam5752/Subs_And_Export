import type React from "react";
import type { Cue } from "@/components/SubtitleOverlay";
import type { PreviewPlayerHandle } from "@/components/PreviewPlayer";
import type { JobResponse } from "@/lib/api";
import type { TranscribeMode, TranscribeProvider } from "./processTypes";

export interface ProcessingOptions {
  transcribeMode: TranscribeMode;
  transcribeProvider: TranscribeProvider;
  sourceDurationSeconds?: number | null;
  outputQuality: "low size" | "balanced" | "high quality";
  outputResolution: "1080x1920" | "2160x3840" | "";
  contextPrompt: string;
  subtitle_position: number;
  max_subtitle_lines: number;
  subtitle_color: string;
  shadow_strength: number;
  highlight_style: string;
  subtitle_size: number;
  karaoke_enabled: boolean;
  watermark_enabled: boolean;
}

export interface VideoInfo {
  width: number;
  height: number;
  aspectWarning: boolean;
  thumbnailUrl: string | null;
  durationSeconds: number;
}

export interface ProcessContextType {
  // Props passed from parent
  selectedFile: File | null;
  onFileSelect: (file: File | null) => void;
  isProcessing: boolean;
  progress: number;
  statusMessage: string;
  error: string;
  onStartProcessing: (options: ProcessingOptions) => Promise<void>;
  onReprocessJob: (
    sourceJobId: string,
    options: ProcessingOptions,
  ) => Promise<void>;
  onReset: () => void;
  onCancelProcessing?: () => void;
  selectedJob: JobResponse | null;
  onJobSelect: (job: JobResponse | null) => void;
  onRefreshJobs?: () => Promise<void>;
  statusStyles: Record<string, string>;
  buildStaticUrl: (path?: string | null) => string | null;
  hasVideos: boolean;
  hasActiveJob: boolean;
  transcribeMode: TranscribeMode;
  transcribeProvider: TranscribeProvider;

  // Local state
  subtitlePosition: number;
  setSubtitlePosition: (v: number) => void;
  maxSubtitleLines: number;
  setMaxSubtitleLines: (v: number) => void;
  subtitleColor: string;
  setSubtitleColor: (v: string) => void;
  subtitleSize: number;
  setSubtitleSize: (v: number) => void;
  karaokeEnabled: boolean;
  watermarkEnabled: boolean;
  shadowStrength: number;
  activeSidebarTab: "transcript" | "styles";
  setActiveSidebarTab: (v: "transcript" | "styles") => void;
  videoInfo: VideoInfo | null;
  setVideoInfo: (v: VideoInfo | null) => void;
  previewVideoUrl: string | null;
  setPreviewVideoUrl: (url: string | null) => void;
  videoUrl: string | null;
  cues: Cue[];
  setCues: (cues: Cue[]) => void;
  processedCues: Cue[];

  // Derived/Refs
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  resultsRef: React.RefObject<HTMLDivElement | null>;
  transcriptContainerRef: React.RefObject<HTMLDivElement | null>;
  playerRef: React.RefObject<PreviewPlayerHandle | null>;

  // Step management
  currentStep: number;
  setOverrideStep: (step: number | null) => void;
  overrideStep: number | null;

  // Actions
  handleStart: () => void;
  handleExport: (resolution: string) => Promise<void>;
  exportingResolutions: Record<string, boolean>;
  exportProgress: Record<string, number | null>;
  exportError: string | null;

  // Transcript editing
  editingCueIndex: number | null;
  setEditingCueIndex: (i: number | null) => void;
  editingCueSurface: "video" | "transcript" | null;
  editingCueDraft: string;
  setEditingCueDraft: (s: string) => void;
  isSavingTranscript: boolean;
  transcriptLoadError: string | null;
  transcriptSaveError: string | null;
  setTranscriptSaveError: (s: string | null) => void;
  beginEditingCue: (index: number, surface?: "video" | "transcript") => void;
  cancelEditingCue: () => void;
  saveEditingCue: () => Promise<void>;
  updateCueText: (cue: Cue, nextText: string) => Cue;
  handleUpdateDraft: (text: string) => void;

  // Constants
  SUBTITLE_COLORS: Array<{ label: string; value: string; ass: string }>;
}
