import { useLayoutEffect, useMemo, type MutableRefObject } from "react";
import type { Cue } from "@/components/SubtitleOverlay";
import type { JobResponse } from "@/lib/api";
import { resegmentCues } from "@/lib/subtitleUtils";
import { resolveConfiguredTranscription } from "@/lib/transcription";

export function getTranscriptionRoute() {
  const configured = resolveConfiguredTranscription(
    process.env.NEXT_PUBLIC_TRANSCRIBE_PROVIDER,
    process.env.NEXT_PUBLIC_TRANSCRIBE_MODE,
  );
  return [configured.mode, configured.provider] as const;
}

export function useProcessedCues(
  cues: Cue[],
  maxSubtitleLines: number,
  subtitleSize: number,
): Cue[] {
  return useMemo(
    () => resegmentCues(cues, maxSubtitleLines, subtitleSize),
    [cues, maxSubtitleLines, subtitleSize],
  );
}

export function useSyncJobRefs(
  selectedJobId: string | null,
  selectedJobIdRef: MutableRefObject<string | null>,
  isSavingTranscriptRef: MutableRefObject<boolean>,
): void {
  useLayoutEffect(() => {
    selectedJobIdRef.current = selectedJobId;
    isSavingTranscriptRef.current = false;
    return () => {
      selectedJobIdRef.current = null;
    };
  }, [isSavingTranscriptRef, selectedJobId, selectedJobIdRef]);
}

export function useCalculatedStep(
  selectedJob: JobResponse | null,
  selectedFile: File | null,
  isProcessing: boolean,
): number {
  return useMemo(() => {
    if (selectedJob?.status === "completed") return 3;
    if (selectedFile || selectedJob || isProcessing) return 2;
    return 1;
  }, [isProcessing, selectedFile, selectedJob]);
}
