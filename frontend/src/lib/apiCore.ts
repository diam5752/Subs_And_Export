import {
  isProcessingCreditTier,
  type ProcessingCreditTier,
} from "@/lib/points";
import { reportApiFailure } from "@/lib/observability";

// An explicitly empty production value keeps every API request same-origin.
// That makes the standalone image portable across verified hostnames without
// rebuilding it for each public URL. Development still keeps its local API
// fallback when the variable is completely absent.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "production" ? "" : "http://localhost:8080");

type ApiErrorDetails = Readonly<Record<string, unknown>>;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: ApiErrorDetails | null;

  constructor(
    message: string,
    status: number,
    code: string | null = null,
    details: ApiErrorDetails | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function requestTimeoutError(): ApiError {
  return new ApiError(
    "Request timed out. Check your connection and try again.",
    0,
    "request_timeout",
  );
}

export function throwReportedApiFailure(
  endpoint: string,
  error: unknown,
): never {
  reportApiFailure(endpoint, error);
  throw error;
}

export interface UploadCallbacks {
  onProgress?: (percent: number) => void;
  onUploadComplete?: () => void;
  signal?: AbortSignal;
}

export interface ProcessVideoSettings {
  authorized_credits: ProcessingCreditTier;
  transcribe_tier?: string;
  transcribe_provider?: string;
  openai_model?: string;
  video_quality?: string;
  video_resolution?: string;
  context_prompt?: string;
  subtitle_position?: number;
  max_subtitle_lines?: number;
  subtitle_color?: string;
  shadow_strength?: number;
  highlight_style?: string;
  subtitle_size?: number;
  karaoke_enabled?: boolean;
  watermark_enabled?: boolean;
}

export const STREAM_UPLOAD_METADATA_HEADER_MAX_CHARS = 8_000;
export const API_REQUEST_TIMEOUT_MS = 12_000;

export function requireAuthorizedCredits(value: unknown): ProcessingCreditTier {
  if (!isProcessingCreditTier(value)) {
    throw new ApiError(
      "Processing requires an explicitly confirmed credit ceiling.",
      0,
      "invalid_authorized_credits",
    );
  }
  return value;
}

export function encodeUtf8Base64(value: string): string | null {
  try {
    const binary = encodeURIComponent(value).replace(
      /%([0-9A-F]{2})/g,
      (_match, hex: string) => String.fromCharCode(Number.parseInt(hex, 16)),
    );
    return btoa(binary);
  } catch {
    return null;
  }
}

export function normalizedProcessVideoSettings(settings: ProcessVideoSettings) {
  return {
    authorized_credits: requireAuthorizedCredits(settings.authorized_credits),
    transcribe_tier: settings.transcribe_tier || "standard",
    transcribe_provider: settings.transcribe_provider || "mock",
    openai_model: settings.openai_model || "",
    video_quality: settings.video_quality || "balanced",
    video_resolution: settings.video_resolution || "",
    context_prompt: settings.context_prompt || "",
    subtitle_position: settings.subtitle_position ?? 16,
    max_subtitle_lines: settings.max_subtitle_lines ?? 2,
    subtitle_color: settings.subtitle_color ?? null,
    shadow_strength: settings.shadow_strength ?? 4,
    highlight_style: settings.highlight_style || "karaoke",
    subtitle_size: settings.subtitle_size ?? 100,
    karaoke_enabled: settings.karaoke_enabled ?? true,
    watermark_enabled: settings.watermark_enabled ?? false,
  };
}

export function uploadCancelledError(): ApiError {
  return new ApiError("Upload cancelled", 0, "upload_cancelled");
}

export function uploadNetworkError(): ApiError {
  return new ApiError("Upload failed", 0, "upload_network_error");
}

export function parseXhrPayload(xhr: XMLHttpRequest): unknown {
  if (typeof xhr.response === "object" && xhr.response !== null) {
    return xhr.response;
  }
  const responseText =
    typeof xhr.responseText === "string" ? xhr.responseText : "";
  if (!responseText) return null;
  try {
    return JSON.parse(responseText) as unknown;
  } catch {
    return responseText;
  }
}

export function apiErrorFromPayload(
  payload: unknown,
  status: number,
  fallbackMessage: string,
): ApiError {
  if (typeof payload === "string" && payload) {
    return new ApiError(payload, status, null, null);
  }
  if (typeof payload !== "object" || payload === null) {
    return new ApiError(fallbackMessage, status, null, null);
  }

  const errorData = payload as Record<string, unknown>;
  const code = typeof errorData.code === "string" ? errorData.code : null;
  const message = apiErrorMessage(errorData, fallbackMessage, code);
  const details = apiErrorDetails(errorData.details);

  return new ApiError(message, status, code, details);
}

function apiErrorMessage(
  errorData: Record<string, unknown>,
  fallbackMessage: string,
  code: string | null,
): string {
  let message = fallbackMessage;
  if (typeof errorData.detail === "string") {
    message = errorData.detail;
  } else if (errorData.detail !== undefined) {
    message = JSON.stringify(errorData.detail);
  } else if (typeof errorData.message === "string") {
    message = errorData.message;
  }
  return code && errorData.detail !== undefined
    ? `${message} [${code}]`
    : message;
}

function apiErrorDetails(value: unknown): ApiErrorDetails | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return { ...(value as Record<string, unknown>) };
}
