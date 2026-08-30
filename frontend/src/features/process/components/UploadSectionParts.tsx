import Image from "next/image";
import React from "react";
import { TokenIcon } from "@/components/icons";
import type { useI18n } from "@/context/I18nContext";
import { JobResponse } from "@/lib/api";
import { formatPoints } from "@/lib/points";
import { resolveTranscriptionTier } from "@/lib/transcription";
import type { TranscribeMode } from "../processTypes";

type Translate = ReturnType<typeof useI18n>["t"];

export function HiddenVideoInput({
  inputRef,
  disabled,
  onChange,
}: {
  inputRef: React.RefObject<HTMLInputElement | null>;
  disabled: boolean;
  onChange: React.ChangeEventHandler<HTMLInputElement>;
}) {
  return (
    <input
      ref={inputRef}
      type="file"
      accept="video/mp4,video/quicktime,video/x-matroska"
      onChange={onChange}
      className="hidden"
      disabled={disabled}
    />
  );
}

export function UploadValidationError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)] animate-fade-in">
      {message}
    </div>
  );
}

export function UploadRetentionNote({ t }: { t: Translate }) {
  return (
    <p className="studio-upload-retention-note flex items-center justify-center gap-1.5 px-3 text-center text-[11px] font-medium leading-5 text-[var(--muted)]">
      <svg
        className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M7 10V8a5 5 0 0 1 10 0v2m-9 0h8a2 2 0 0 1 2 2v7H6v-7a2 2 0 0 1 2-2Z"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {t("temporaryWorkspaceUploadNote")}
    </p>
  );
}

export function SelectedVideoThumbnail({
  thumbnailUrl,
  videoUrl,
  isCompleted,
  t,
}: {
  thumbnailUrl?: string | null;
  videoUrl: string | null;
  isCompleted: boolean;
  t: Translate;
}) {
  let media: React.ReactNode = (
    <div className="h-full w-full flex items-center justify-center bg-emerald-900/20">
      <svg
        className="w-8 h-8 text-emerald-500/40"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1}
          d="M15 10l4.553-2.276A1 1 0 0121 8.818v6.364a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
        />
      </svg>
    </div>
  );
  if (thumbnailUrl) {
    media = (
      <Image
        src={thumbnailUrl}
        alt={t("videoThumbnailAlt")}
        fill
        unoptimized
        className="object-cover opacity-80 transition-opacity group-hover:opacity-100"
        sizes="64px"
      />
    );
  } else if (videoUrl) {
    media = (
      <video
        src={videoUrl}
        className="w-full h-full object-cover opacity-80 transition-opacity group-hover:opacity-100"
        muted
        playsInline
        loop
        onMouseOver={(event) =>
          event.currentTarget.play().catch(() => undefined)
        }
        onMouseOut={(event) => event.currentTarget.pause()}
      />
    );
  }
  return (
    <div className="relative h-16 w-16 shrink-0 rounded-lg overflow-hidden bg-black/20 border border-emerald-500/20 group">
      {media}
      {isCompleted && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-8 h-8 rounded-full bg-emerald-500/80 shadow-lg shadow-emerald-500/40 flex items-center justify-center text-white transform scale-100 group-hover:scale-110 transition-transform backdrop-blur-[1px]">
            <svg
              className="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={3}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
        </div>
      )}
    </div>
  );
}

function ViewResultsButton({
  onViewResults,
  t,
}: {
  onViewResults: () => void;
  t: Translate;
}) {
  return (
    <button
      onClick={(event) => {
        event.stopPropagation();
        onViewResults();
      }}
      className="px-4 py-1.5 text-xs font-bold rounded-lg bg-emerald-500 text-white hover:brightness-110 shadow-lg shadow-emerald-500/20 transition-all active:scale-95 flex items-center gap-2"
    >
      <span>{t("viewResults")}</span>
      <svg
        className="w-3 h-3"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M19 9l-7 7-7-7"
        />
      </svg>
    </button>
  );
}

export function ProcessingActionButton({
  isProcessing,
  selectedFile,
  selectedJob,
  transcribeMode,
  isVideoValidationPending,
  fileValidationError,
  selectedCost,
  onViewResults,
  onStart,
  t,
}: {
  isProcessing: boolean;
  selectedFile: File | null;
  selectedJob: JobResponse | null;
  transcribeMode: TranscribeMode;
  isVideoValidationPending: boolean;
  fileValidationError: string | null;
  selectedCost: number;
  onViewResults: () => void;
  onStart: () => void;
  t: Translate;
}) {
  if (isProcessing) return null;
  const jobTier = resolveTranscriptionTier(
    selectedJob?.result_data?.transcribe_tier,
  );
  const matchesCompletedJob =
    selectedJob?.status === "completed" && jobTier === transcribeMode;
  if (matchesCompletedJob) {
    return <ViewResultsButton onViewResults={onViewResults} t={t} />;
  }
  if (!selectedFile && !selectedJob) return null;
  const isDisabled = isVideoValidationPending || Boolean(fileValidationError);
  return (
    <button
      disabled={isDisabled}
      aria-busy={isVideoValidationPending || undefined}
      onClick={(event) => {
        event.stopPropagation();
        if (!isDisabled) onStart();
      }}
      className={`group px-5 py-2 text-xs font-bold rounded-lg transition-all active:scale-95 flex items-center gap-2 ${
        isDisabled
          ? "bg-[var(--border)] text-[var(--muted)] cursor-not-allowed"
          : "bg-[var(--accent)] text-[var(--background)] hover:brightness-110 shadow-lg shadow-[var(--accent)]/20"
      }`}
    >
      <span>{t("startProcessing")}</span>
      <div className="flex items-center gap-1.5 opacity-80 border-l border-current/20 pl-2 ml-0.5">
        <TokenIcon className="w-3.5 h-3.5" />
        <span className="font-mono">{formatPoints(selectedCost)}</span>
      </div>
    </button>
  );
}

export function ProcessingProgress({
  isProcessing,
  progress,
  statusMessage,
  onCancel,
  t,
}: {
  isProcessing: boolean;
  progress: number;
  statusMessage: string;
  onCancel?: () => void;
  t: Translate;
}) {
  if (!isProcessing) return null;
  return (
    <div
      role="progressbar"
      aria-valuenow={progress}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-labelledby="progress-label"
      className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 space-y-3 animate-fade-in mt-4"
    >
      <div className="flex items-center justify-between text-sm">
        <span id="progress-label" className="font-medium">
          {statusMessage || t("progressLabel")}
        </span>
        <span className="text-[var(--accent)] font-semibold">{progress}%</span>
      </div>
      <progress
        className="upload-progress"
        value={progress}
        max={100}
        aria-hidden="true"
        tabIndex={-1}
      />
      {onCancel && (
        <div className="flex justify-end pt-1">
          <button
            onClick={(event) => {
              event.stopPropagation();
              onCancel();
            }}
            className="px-4 py-1.5 rounded-lg text-sm font-medium bg-[var(--danger)]/10 text-[var(--danger)] hover:bg-[var(--danger)]/20 border border-[var(--danger)]/30 transition-colors"
          >
            {t("cancelProcessing")}
          </button>
        </div>
      )}
    </div>
  );
}
