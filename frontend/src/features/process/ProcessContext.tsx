import React, {
  createContext,
  useContext,
  useMemo,
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
  useCallback,
} from "react";
import { API_BASE, JobResponse, api } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Cue } from "@/components/SubtitleOverlay";
import { resegmentCues, updateCueText } from "@/lib/subtitleUtils";
import { PreviewPlayerHandle } from "@/components/PreviewPlayer";
import type { TranscribeMode, TranscribeProvider } from "./processTypes";
import type {
  ProcessContextType,
  ProcessingOptions,
  VideoInfo,
} from "./ProcessContextTypes";
export type { ProcessingOptions } from "./ProcessContextTypes";
import { resolveConfiguredTranscription } from "@/lib/transcription";
import { buildSubtitleExportFilename } from "@/lib/exportFilename";
import { downloadArtifactWithGrant } from "@/lib/artifactDownload";
import { exportFormatBucket, reportProductAction } from "@/lib/observability";
import { videoQualityForResolution } from "./processSettings";
import { useCueResource } from "./useCueResource";
import { useSubtitlePreferences } from "./useSubtitlePreferences";

const ProcessContext = createContext<ProcessContextType | undefined>(undefined);

export function useProcessContext() {
  const context = useContext(ProcessContext);
  if (!context) {
    throw new Error("useProcessContext must be used within a ProcessProvider");
  }
  return context;
}

interface ProcessProviderProps {
  children: React.ReactNode;
  // Parent props
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
  totalJobs: number;
}

function startExportProgressPolling(
  exportJobId: string,
  resolution: string,
  selectedJobIdRef: React.MutableRefObject<string | null>,
  setExportProgress: React.Dispatch<
    React.SetStateAction<Record<string, number | null>>
  >,
): number {
  let pollInFlight = false;
  let renderProgressObserved = false;
  return window.setInterval(() => {
    if (pollInFlight || selectedJobIdRef.current !== exportJobId) return;
    pollInFlight = true;
    void api
      .getJobStatus(exportJobId)
      .then((job) => {
        if (selectedJobIdRef.current !== exportJobId) return;
        const rawProgress = job.progress ?? 0;
        if (rawProgress <= 0) return;
        if (rawProgress >= 100 && !renderProgressObserved) return;
        renderProgressObserved = true;
        const value = Math.max(1, Math.min(99, rawProgress));
        setExportProgress((previous) => ({
          ...previous,
          [resolution]: value,
        }));
      })
      .catch(() => undefined)
      .finally(() => {
        pollInFlight = false;
      });
  }, 750);
}

async function downloadFinishedExport(
  updatedJob: JobResponse,
  fallbackFilename: string | null | undefined,
  resolution: string,
  subtitleFileFormats: Set<string>,
  buildStaticUrl: (path?: string | null) => string | null,
): Promise<void> {
  const artifactPath = updatedJob.result_data?.variants?.[resolution];
  if (!artifactPath) return;
  const extension = subtitleFileFormats.has(resolution) ? resolution : "mp4";
  const downloadFilename = buildSubtitleExportFilename(
    updatedJob.result_data?.original_filename ?? fallbackFilename,
    extension,
  );
  await downloadArtifactWithGrant(
    updatedJob.id,
    artifactPath,
    downloadFilename,
    buildStaticUrl,
  );
}

export function ProcessProvider({
  children,
  selectedFile,
  onFileSelect,
  isProcessing,
  progress,
  statusMessage,
  error,
  onStartProcessing,
  onReprocessJob,
  onReset,
  onCancelProcessing,
  selectedJob,
  onJobSelect,
  onRefreshJobs,
  statusStyles,
  buildStaticUrl,
  totalJobs,
}: ProcessProviderProps) {
  const { t } = useI18n();

  // Public configuration selects only the requested UI route. The backend
  // independently enforces feature flags, provider scope, credentials, and budgets.
  // Missing or invalid configuration always fails closed to the mock engine.
  const configuredTranscription = resolveConfiguredTranscription(
    process.env.NEXT_PUBLIC_TRANSCRIBE_PROVIDER,
    process.env.NEXT_PUBLIC_TRANSCRIBE_MODE,
  );
  const transcribeMode: TranscribeMode = configuredTranscription.mode;
  const transcribeProvider: TranscribeProvider =
    configuredTranscription.provider;

  const {
    subtitlePosition,
    setSubtitlePosition,
    maxSubtitleLines,
    setMaxSubtitleLines,
    subtitleColor,
    setSubtitleColor,
    subtitleSize,
    setSubtitleSize,
    karaokeEnabled,
    watermarkEnabled,
    shadowStrength,
    SUBTITLE_COLORS,
    persistSubtitleSettings,
  } = useSubtitlePreferences(t);

  const [activeSidebarTab, setActiveSidebarTab] = useState<
    "transcript" | "styles"
  >("transcript");

  const [videoInfo, setVideoInfo] = useState<VideoInfo | null>(null);
  const [previewVideoUrl, setPreviewVideoUrl] = useState<string | null>(null);
  const transcriptionSource =
    selectedJob?.result_data?.transcription_url ?? null;
  const {
    cues,
    error: transcriptLoadError,
    setCues,
    setCueResource,
  } = useCueResource(transcriptionSource);

  const [overrideStep, setOverrideStepState] = useState<number | null>(null);
  const [exportingResolutions, setExportingResolutions] = useState<
    Record<string, boolean>
  >({});
  const [exportProgress, setExportProgress] = useState<
    Record<string, number | null>
  >({});
  const [exportError, setExportError] = useState<string | null>(null);

  // Transcript editing state
  const [editingCueIndex, setEditingCueIndex] = useState<number | null>(null);
  const [editingCueSurface, setEditingCueSurface] = useState<
    "video" | "transcript" | null
  >(null);
  const [editingCueDraft, setEditingCueDraft] = useState<string>("");
  const [isSavingTranscript, setIsSavingTranscript] = useState(false);
  const [transcriptSaveError, setTranscriptSaveError] = useState<string | null>(
    null,
  );
  const selectedJobId = selectedJob?.id ?? null;
  const selectedJobIdRef = useRef(selectedJobId);
  useLayoutEffect(() => {
    selectedJobIdRef.current = selectedJobId;
    return () => {
      selectedJobIdRef.current = null;
    };
  }, [selectedJobId]);
  const [transientJobId, setTransientJobId] = useState(selectedJobId);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const transcriptContainerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<PreviewPlayerHandle>(null);

  // Derived State
  const processedCues = useMemo(() => {
    return resegmentCues(cues, maxSubtitleLines, subtitleSize);
  }, [cues, maxSubtitleLines, subtitleSize]);

  const calculatedStep = useMemo(() => {
    if (selectedJob?.status === "completed") {
      return 3;
    }
    if (selectedFile || selectedJob || isProcessing) return 2;
    return 1;
  }, [isProcessing, selectedFile, selectedJob]);

  const setOverrideStep = useCallback(
    (step: number | null) => {
      setOverrideStepState(step === calculatedStep ? null : step);
    },
    [calculatedStep],
  );

  const [observedCalculatedStep, setObservedCalculatedStep] =
    useState(calculatedStep);
  if (observedCalculatedStep !== calculatedStep) {
    setObservedCalculatedStep(calculatedStep);
    if (overrideStep === calculatedStep) {
      setOverrideStepState(null);
    }
  }

  // Transient editor/export state belongs to exactly one job. Reset it during
  // the render transition so children never observe the previous job's state.
  if (transientJobId !== selectedJobId) {
    setTransientJobId(selectedJobId);
    setExportingResolutions({});
    setExportProgress({});
    setExportError(null);
    setTranscriptSaveError(null);
    setIsSavingTranscript(false);
    setEditingCueIndex(null);
    setEditingCueSurface(null);
    setEditingCueDraft("");
    setOverrideStepState(null);
  }

  const currentStep = overrideStep ?? calculatedStep;

  const videoUrl = useMemo(() => {
    // Don't return a URL if files are marked as missing on the server
    if (selectedJob?.result_data?.files_missing) {
      return null;
    }
    return buildStaticUrl(
      selectedJob?.result_data?.public_url ||
        selectedJob?.result_data?.video_path,
    );
  }, [buildStaticUrl, selectedJob]);

  // Scroll to results when job completes, BUT only if we are not overriding navigation (e.g. user clicked Step 1/2)
  useEffect(() => {
    if (selectedJob?.status === "completed" && overrideStep === null) {
      // Small timeout to ensure DOM is ready/expanded
      setTimeout(() => {
        resultsRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 100);
    }
  }, [selectedJob?.status, overrideStep]);

  const handleStart = useCallback(() => {
    const colorObj =
      SUBTITLE_COLORS.find((c) => c.value === subtitleColor) ||
      SUBTITLE_COLORS[0];

    if (!selectedFile) {
      if (selectedJob?.status === "completed") {
        void onReprocessJob(selectedJob.id, {
          transcribeMode,
          transcribeProvider,
          sourceDurationSeconds:
            videoInfo?.durationSeconds ??
            selectedJob.result_data?.duration_seconds ??
            null,
          outputQuality: "balanced",
          outputResolution: "",
          contextPrompt: "",
          subtitle_position: subtitlePosition,
          max_subtitle_lines: maxSubtitleLines,
          subtitle_color: colorObj.ass,
          shadow_strength: shadowStrength,
          highlight_style: "active-graphics",
          subtitle_size: subtitleSize,
          karaoke_enabled: karaokeEnabled,
          watermark_enabled: watermarkEnabled,
        });
        return;
      }

      setOverrideStep(2);
      fileInputRef.current?.click();
      return;
    }

    // Stay on Step 2 (caption processing) to show progress. Completion
    // advances to Step 3 automatically via the effect above.

    onStartProcessing({
      transcribeMode,
      transcribeProvider,
      sourceDurationSeconds: videoInfo?.durationSeconds ?? null,
      outputQuality: "balanced",
      outputResolution: "",
      contextPrompt: "",
      subtitle_position: subtitlePosition,
      max_subtitle_lines: maxSubtitleLines,
      subtitle_color: colorObj.ass,
      shadow_strength: shadowStrength,
      highlight_style: "active-graphics",
      subtitle_size: subtitleSize,
      karaoke_enabled: karaokeEnabled,
      watermark_enabled: watermarkEnabled,
    });
  }, [
    SUBTITLE_COLORS,
    karaokeEnabled,
    maxSubtitleLines,
    selectedFile,
    selectedJob,
    onReprocessJob,
    onStartProcessing,
    fileInputRef,
    setOverrideStep,
    shadowStrength,
    subtitleColor,
    subtitlePosition,
    subtitleSize,
    transcribeMode,
    transcribeProvider,
    videoInfo?.durationSeconds,
    watermarkEnabled,
  ]);

  const handleExport = useCallback(
    async (resolution: string) => {
      if (!selectedJob) return;
      const exportJobId = selectedJob.id;
      const format = exportFormatBucket(resolution);

      setExportError(null);
      setExportingResolutions((prev) => ({ ...prev, [resolution]: true }));
      setExportProgress((prev) => ({ ...prev, [resolution]: null }));
      reportProductAction("export_started", {
        outcome: "started",
        exportFormat: format,
      });
      const pollId = startExportProgressPolling(
        exportJobId,
        resolution,
        selectedJobIdRef,
        setExportProgress,
      );
      try {
        const subtitleFileFormats = new Set(["srt", "vtt", "txt"]);
        const colorObj =
          SUBTITLE_COLORS.find((c) => c.value === subtitleColor) ||
          SUBTITLE_COLORS[0];
        const videoQuality = videoQualityForResolution(
          resolution,
          subtitleFileFormats,
        );

        const updatedJob = await api.exportVideo(selectedJob.id, resolution, {
          subtitle_position: subtitlePosition,
          max_subtitle_lines: maxSubtitleLines,
          subtitle_color: colorObj.ass,
          shadow_strength: shadowStrength,
          highlight_style: "active-graphics",
          subtitle_size: subtitleSize,
          karaoke_enabled: karaokeEnabled,
          watermark_enabled: watermarkEnabled,
          video_quality: videoQuality,
        });
        if (selectedJobIdRef.current !== exportJobId) return;
        onJobSelect(updatedJob);
        void onRefreshJobs?.();

        persistSubtitleSettings();

        await downloadFinishedExport(
          updatedJob,
          selectedJob.result_data?.original_filename,
          resolution,
          subtitleFileFormats,
          buildStaticUrl,
        );
        setExportProgress((prev) => ({ ...prev, [resolution]: 100 }));
        reportProductAction("export_completed", {
          outcome: "succeeded",
          exportFormat: format,
        });
      } catch (err) {
        reportProductAction("export_failed", {
          outcome: "failed",
          exportFormat: format,
        });
        if (selectedJobIdRef.current === exportJobId) {
          setExportError(
            err instanceof Error
              ? err.message
              : t("exportVideoError") || "Failed to export file",
          );
        }
      } finally {
        window.clearInterval(pollId);
        if (selectedJobIdRef.current === exportJobId) {
          setExportingResolutions((prev) => ({ ...prev, [resolution]: false }));
        }
      }
    },
    [
      selectedJob,
      onJobSelect,
      onRefreshJobs,
      buildStaticUrl,
      SUBTITLE_COLORS,
      subtitleColor,
      subtitlePosition,
      maxSubtitleLines,
      shadowStrength,
      subtitleSize,
      karaokeEnabled,
      watermarkEnabled,
      persistSubtitleSettings,
      t,
    ],
  );

  const beginEditingCue = useCallback(
    (index: number, surface: "video" | "transcript" = "transcript") => {
      setTranscriptSaveError(null);
      setEditingCueIndex(index);
      setEditingCueSurface(surface);
      setEditingCueDraft(cues[index]?.text ?? "");
    },
    [cues],
  );

  const cancelEditingCue = useCallback(() => {
    setTranscriptSaveError(null);
    setEditingCueIndex(null);
    setEditingCueSurface(null);
    setEditingCueDraft("");
  }, []);

  // Refs for stable callbacks to prevent re-renders on keystrokes/polling
  const editingCueDraftRef = useRef(editingCueDraft);
  const editingCueIndexRef = useRef(editingCueIndex);
  const cuesRef = useRef(cues);

  useEffect(() => {
    editingCueDraftRef.current = editingCueDraft;
    editingCueIndexRef.current = editingCueIndex;
    cuesRef.current = cues;
  }, [editingCueDraft, editingCueIndex, cues]);

  const saveEditingCue = useCallback(async () => {
    const index = editingCueIndexRef.current;
    const draft = editingCueDraftRef.current;
    const currentCues = cuesRef.current;

    if (index === null) return;

    setTranscriptSaveError(null);
    const updatedCues = currentCues.map((cue, idx) => {
      if (idx !== index) return cue;
      return updateCueText(cue, draft);
    });

    setCues(updatedCues);
    if (!selectedJob) {
      setEditingCueIndex(null);
      setEditingCueSurface(null);
      setEditingCueDraft("");
      return;
    }

    const editingJobId = selectedJob.id;
    setIsSavingTranscript(true);
    try {
      await api.updateJobTranscription(editingJobId, updatedCues);
      if (selectedJobIdRef.current !== editingJobId) return;
      void onRefreshJobs?.();
      setEditingCueIndex(null);
      setEditingCueSurface(null);
      setEditingCueDraft("");
      reportProductAction("subtitle_saved", { outcome: "succeeded" });
    } catch (err) {
      if (selectedJobIdRef.current !== editingJobId) return;
      // Keep the editor and server-backed transcript in sync. If persistence
      // fails, restore the last confirmed cues so exports cannot silently use
      // text that the UI only saved locally.
      setCues(currentCues);
      setTranscriptSaveError(
        err instanceof Error
          ? err.message
          : t("transcriptSaveError") || "Unable to save transcript",
      );
    } finally {
      if (selectedJobIdRef.current === editingJobId) {
        setIsSavingTranscript(false);
      }
    }
  }, [onRefreshJobs, selectedJob, setCues, t]);

  const handleUpdateDraft = useCallback((text: string) => {
    setEditingCueDraft(text);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const transcriptionUrl = transcriptionSource;

    if (!transcriptionUrl) {
      return;
    }

    const resolvedUrl = transcriptionUrl.startsWith("http")
      ? transcriptionUrl
      : `${API_BASE}${transcriptionUrl}`;

    fetch(resolvedUrl, { credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch transcription");
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        if (!Array.isArray(data)) {
          throw new Error("Invalid transcription payload");
        }
        setCueResource({
          source: transcriptionUrl,
          cues: data as Cue[],
          error: null,
        });
      })
      .catch(() => {
        if (!cancelled) {
          setCueResource({
            source: transcriptionUrl,
            cues: [],
            error: t("transcriptLoadError"),
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [setCueResource, t, transcriptionSource]);

  const value = {
    selectedFile,
    onFileSelect,
    isProcessing,
    progress,
    statusMessage,
    error,
    onStartProcessing,
    onReprocessJob,
    onReset,
    onCancelProcessing,
    selectedJob,
    onJobSelect,
    statusStyles,
    buildStaticUrl,
    hasVideos: totalJobs > 0,
    hasActiveJob: isProcessing || Boolean(selectedJob),
    transcribeMode,
    transcribeProvider,
    subtitlePosition,
    setSubtitlePosition,
    maxSubtitleLines,
    setMaxSubtitleLines,
    subtitleColor,
    setSubtitleColor,
    subtitleSize,
    setSubtitleSize,
    karaokeEnabled,
    watermarkEnabled,
    shadowStrength,
    activeSidebarTab,
    setActiveSidebarTab,
    videoInfo,
    setVideoInfo,
    previewVideoUrl,
    setPreviewVideoUrl,
    videoUrl,
    cues,
    setCues,
    processedCues,
    fileInputRef,
    resultsRef,
    transcriptContainerRef,
    playerRef,
    currentStep,
    setOverrideStep,
    overrideStep,
    handleStart,
    handleExport,
    exportingResolutions,
    exportProgress,
    exportError,
    editingCueIndex,
    setEditingCueIndex,
    editingCueSurface,
    editingCueDraft,
    setEditingCueDraft,
    isSavingTranscript,
    transcriptLoadError,
    transcriptSaveError,
    setTranscriptSaveError,
    beginEditingCue,
    cancelEditingCue,
    saveEditingCue,
    updateCueText,
    handleUpdateDraft,
    SUBTITLE_COLORS,
  };

  return (
    <ProcessContext.Provider value={value}>{children}</ProcessContext.Provider>
  );
}
