import type { MessageKey } from "@/context/i18nMessages";
import type { ProcessingOptions } from "@/features/process/ProcessView";
import {
  isProcessingCreditTier,
  type ProcessingCreditTier,
} from "@/lib/points";
import { reportProductAction } from "@/lib/observability";

export const RESTORABLE_ACTIVE_JOB_STATUSES = new Set([
  "pending",
  "processing",
  "cancelling",
]);
export const CANCELLABLE_JOB_STATUSES = new Set(["pending", "processing"]);
export const ELEVENLABS_MISSING_WORD_TIMESTAMPS =
  "ElevenLabs Scribe v2 response did not include word timestamps.";

export type PendingProcessingAction =
  | {
      kind: "new";
      options: ProcessingOptions;
      authorizedCredits?: ProcessingCreditTier;
    }
  | {
      kind: "reprocess";
      sourceJobId: string;
      options: ProcessingOptions;
      authorizedCredits?: ProcessingCreditTier;
    };

interface ProcessingQuoteChange {
  durationSeconds: number;
  requiredCredits: ProcessingCreditTier;
}

export function processingSettings(
  options: ProcessingOptions,
  authorizedCredits: ProcessingCreditTier,
  includeSourceDuration = false,
) {
  const settings = {
    authorized_credits: authorizedCredits,
    transcribe_tier: options.transcribeMode || "standard",
    transcribe_provider: options.transcribeProvider || "mock",
    video_quality: options.outputQuality,
    video_resolution: options.outputResolution,
    context_prompt: options.contextPrompt,
    subtitle_position: options.subtitle_position,
    max_subtitle_lines: options.max_subtitle_lines,
    subtitle_color: options.subtitle_color,
    shadow_strength: options.shadow_strength,
    highlight_style: options.highlight_style,
    subtitle_size: options.subtitle_size,
    karaoke_enabled: options.karaoke_enabled,
    watermark_enabled: options.watermark_enabled,
  };
  return includeSourceDuration
    ? {
        ...settings,
        source_duration_seconds: options.sourceDurationSeconds ?? null,
      }
    : settings;
}

type Translate = (
  key: MessageKey,
  params?: Record<string, string | number>,
) => string;
const UPLOAD_FAILURE_MESSAGES: Readonly<Record<string, MessageKey>> = {
  upload_cancelled: "processingCancelled",
  upload_network_error: "uploadConnectionError",
  upload_timeout: "uploadConnectionError",
  upload_http_error: "uploadFailed",
};

function uploadErrorDetails(error: unknown): {
  code: string;
  status: number | null;
} {
  if (typeof error !== "object" || error === null)
    return { code: "", status: null };
  const value = error as { code?: unknown; status?: unknown };
  return {
    code: typeof value.code === "string" ? value.code : "",
    status: typeof value.status === "number" ? value.status : null,
  };
}

export function uploadFailureMessage(
  error: unknown,
  aborted: boolean,
  t: Translate,
): string {
  if (aborted) return t("processingCancelled");
  const details = uploadErrorDetails(error);
  const messageKey = UPLOAD_FAILURE_MESSAGES[details.code];
  if (messageKey) return t(messageKey);
  if (details.status === 408) return t("uploadConnectionError");
  return error instanceof Error ? error.message : t("startProcessingError");
}

export function reportProcessingFailure(
  aborted: boolean,
  quoteReopened: boolean,
): void {
  if (!aborted && !quoteReopened) {
    reportProductAction("processing_failed", { outcome: "failed" });
  }
}

export function processingQuoteChangeFromError(
  error: unknown,
): ProcessingQuoteChange | null {
  if (typeof error !== "object" || error === null) return null;
  const candidate = error as Record<string, unknown>;
  if (
    candidate.status !== 409 ||
    candidate.code !== "PROCESSING_QUOTE_CHANGED"
  ) {
    return null;
  }
  if (
    typeof candidate.details !== "object" ||
    candidate.details === null ||
    Array.isArray(candidate.details)
  )
    return null;

  const details = candidate.details as Record<string, unknown>;
  const durationSeconds = details.duration_seconds;
  const requiredCredits = details.required_credits;
  if (
    typeof durationSeconds !== "number" ||
    !Number.isFinite(durationSeconds) ||
    durationSeconds <= 0 ||
    !isProcessingCreditTier(requiredCredits)
  )
    return null;

  return { durationSeconds, requiredCredits };
}
