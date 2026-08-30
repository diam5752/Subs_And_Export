import React, {
  useMemo,
  useState,
  useCallback,
  useEffect,
  useEffectEvent,
} from "react";
import { useI18n } from "@/context/I18nContext";
import { useProcessContext } from "../ProcessContext";
import { validateVideoAspectRatio } from "@/lib/video";
import {
  MAX_VIDEO_DURATION_LABEL,
  MAX_VIDEO_DURATION_SECONDS,
  VideoCreditPricing,
  resolveVideoCreditPricing,
} from "./VideoCreditPricing";
import {
  HiddenVideoInput,
  ProcessingActionButton,
  ProcessingProgress,
  SelectedVideoThumbnail,
  UploadRetentionNote,
  UploadValidationError,
} from "./UploadSectionParts";
import { CompactFileIndicator } from "./CompactFileIndicator";

const DEFAULT_MAX_UPLOAD_MB = 500;
const parsedMaxUploadMb = Number(
  process.env.NEXT_PUBLIC_MAX_UPLOAD_MB ?? DEFAULT_MAX_UPLOAD_MB,
);
const MAX_UPLOAD_MB =
  Number.isFinite(parsedMaxUploadMb) && parsedMaxUploadMb > 0
    ? Math.floor(parsedMaxUploadMb)
    : DEFAULT_MAX_UPLOAD_MB;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
const ALLOWED_VIDEO_EXT = /\.(mp4|mov|mkv)$/i;

type FileValidationErrorKind =
  | "unsupported-type"
  | "file-too-large"
  | "duration-unreadable"
  | "duration-too-long";

function completedJobHasVideoData(
  selectedJob: ReturnType<typeof useProcessContext>["selectedJob"],
): boolean {
  if (selectedJob?.status !== "completed") return false;
  return Boolean(
    selectedJob.result_data && !selectedJob.result_data.files_missing,
  );
}

function selectedVideoFileSize(
  selectedFile: File | null,
  selectedJob: ReturnType<typeof useProcessContext>["selectedJob"],
): string {
  if (selectedFile?.size) return (selectedFile.size / (1024 * 1024)).toFixed(1);
  const outputSize = selectedJob?.result_data?.output_size;
  return outputSize ? (outputSize / (1024 * 1024)).toFixed(1) : "--";
}

export function UploadSection() {
  const { t } = useI18n();

  const {
    selectedFile,
    onFileSelect,
    isProcessing,
    currentStep,
    setOverrideStep,
    onJobSelect,
    handleStart,
    fileInputRef,
    videoInfo,
    setVideoInfo,
    setPreviewVideoUrl,
    setCues,
    selectedJob,
    error,
    progress,
    statusMessage,
    onCancelProcessing,
    videoUrl,
    transcribeMode,
    transcribeProvider,
  } = useProcessContext();

  const [isDragOver, setIsDragOver] = useState(false);
  const [fileValidationErrorKind, setFileValidationErrorKind] =
    useState<FileValidationErrorKind | null>(null);
  const [validatedFile, setValidatedFile] = useState<File | null>(null);
  // Step 1 starts with a compact summary for an existing file. Step 2 expands
  // the same input summary to show processing controls and progress.
  const [collapsePreference, setCollapsePreference] = useState<{
    step: number;
    collapsed: boolean;
  } | null>(null);
  const validationRequestId = React.useRef(0);
  const isVideoValidationPending =
    selectedFile !== null && validatedFile !== selectedFile;
  const fileValidationError = useMemo(() => {
    switch (fileValidationErrorKind) {
      case "unsupported-type":
        return t("uploadUnsupportedType");
      case "file-too-large":
        return t("uploadFileTooLarge", { size: MAX_UPLOAD_MB });
      case "duration-unreadable":
        return t("uploadDurationUnreadable");
      case "duration-too-long":
        return t("uploadDurationTooLong", {
          duration: MAX_VIDEO_DURATION_LABEL,
        });
      default:
        return null;
    }
  }, [fileValidationErrorKind, t]);

  const localCollapsed =
    collapsePreference?.step === currentStep
      ? collapsePreference.collapsed
      : currentStep === 1;
  const isExpanded = !localCollapsed || isProcessing;
  const pricingDuration =
    videoInfo?.durationSeconds ??
    selectedJob?.result_data?.duration_seconds ??
    null;
  const videoPricing = resolveVideoCreditPricing(
    pricingDuration,
    transcribeProvider,
    transcribeMode,
  );
  const hasJobData = completedJobHasVideoData(selectedJob);
  const hasCompactView = Boolean(selectedFile || hasJobData || currentStep > 2);
  const fileName =
    selectedFile?.name ||
    selectedJob?.result_data?.original_filename ||
    t("processedVideoFallback");
  const fileSize = selectedVideoFileSize(selectedFile, selectedJob);

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0] || null;
      setFileValidationErrorKind(null);
      if (file) {
        if (!ALLOWED_VIDEO_EXT.test(file.name)) {
          setFileValidationErrorKind("unsupported-type");
          return;
        }
        if (file.size > MAX_UPLOAD_BYTES) {
          setFileValidationErrorKind("file-too-large");
          return;
        }
        onFileSelect(file);
      }
    },
    [onFileSelect],
  );

  const handleUploadCardClick = useCallback(() => {
    if (!isProcessing) {
      fileInputRef.current?.click();
    }
  }, [isProcessing, fileInputRef]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, callback: () => void) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        callback();
      }
    },
    [],
  );

  const handleDragEnter = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (!isProcessing) {
        setIsDragOver(true);
      }
    },
    [isProcessing],
  );

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget === e.target) {
      setIsDragOver(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      if (isProcessing) return;

      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        const file = files[0];
        setFileValidationErrorKind(null);
        if (!ALLOWED_VIDEO_EXT.test(file.name)) {
          setFileValidationErrorKind("unsupported-type");
          return;
        }
        if (file.size > MAX_UPLOAD_BYTES) {
          setFileValidationErrorKind("file-too-large");
          return;
        }
        onFileSelect(file);
        setOverrideStep(null);
      }
    },
    [isProcessing, onFileSelect, setOverrideStep],
  );

  const clearSelectedVideoState = useEffectEvent(() => {
    setVideoInfo(null);
    setPreviewVideoUrl(null);
    setCues([]);
    setFileValidationErrorKind(null);
    setValidatedFile(null);
  });

  const prepareSelectedVideoState = useEffectEvent((blobUrl: string) => {
    setVideoInfo(null);
    setPreviewVideoUrl(blobUrl);
    setCues([]);
    setFileValidationErrorKind(null);
    setValidatedFile(null);
  });

  const commitSelectedVideoValidation = useEffectEvent(
    (
      file: File,
      info: Awaited<ReturnType<typeof validateVideoAspectRatio>>,
    ) => {
      setVideoInfo(info);
      if (info.durationSeconds <= 0) {
        setFileValidationErrorKind("duration-unreadable");
      } else if (info.durationSeconds > MAX_VIDEO_DURATION_SECONDS) {
        setFileValidationErrorKind("duration-too-long");
      }
      setValidatedFile(file);
    },
  );

  // Effect for validating video when selectedFile changes
  useEffect(() => {
    let isCancelled = false;
    const requestId = ++validationRequestId.current;
    const validationController = new AbortController();

    if (!selectedFile) {
      queueMicrotask(() => {
        if (isCancelled || requestId !== validationRequestId.current) return;
        clearSelectedVideoState();
      });
      return () => {
        isCancelled = true;
        validationController.abort();
      };
    }

    const blobUrl = URL.createObjectURL(selectedFile);
    queueMicrotask(() => {
      if (isCancelled || requestId !== validationRequestId.current) return;
      prepareSelectedVideoState(blobUrl);
    });

    void validateVideoAspectRatio(
      selectedFile,
      validationController.signal,
    ).then((info) => {
      if (!isCancelled && requestId === validationRequestId.current) {
        commitSelectedVideoValidation(selectedFile, info);
      }
    });

    return () => {
      isCancelled = true;
      validationController.abort();
      URL.revokeObjectURL(blobUrl);
    };
  }, [selectedFile]);

  const handleSummaryToggle = useCallback(() => {
    if (!isProcessing) {
      setCollapsePreference({ step: currentStep, collapsed: !localCollapsed });
    }
  }, [currentStep, isProcessing, localCollapsed]);

  return useMemo(() => {
    const { selectedQuote, selectedCost, selectedDurationAvailable } =
      videoPricing;
    if (hasCompactView) {
      return (
        <>
          <HiddenVideoInput
            inputRef={fileInputRef}
            onChange={handleFileChange}
            disabled={isProcessing}
          />
          <div
            id="upload-section-compact"
            data-testid="upload-section"
            className="card space-y-4 scroll-mt-32 animate-fade-in-up-scale"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div
                role="button"
                tabIndex={0}
                aria-expanded={isExpanded}
                aria-controls="input-video-details"
                aria-label={t("inputVideoSummaryToggle")}
                onKeyDown={(e) => handleKeyDown(e, handleSummaryToggle)}
                className={`flex items-center gap-3 transition-all duration-300 cursor-pointer group/step focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:rounded-full focus-visible:outline-none ${isExpanded ? "scale-[1.01]" : "hover:scale-[1.005]"}`}
                onClick={handleSummaryToggle}
              >
                <h3 className="text-xl font-semibold">
                  {t("inputVideoTitle")}
                </h3>
                {/* Chevron indicator for expand/collapse */}
                <svg
                  className={`w-5 h-5 text-[var(--muted)] transition-transform duration-300 ${isExpanded ? "rotate-180" : ""}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  data-testid="input-video-chevron"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 9l-7 7-7-7"
                  />
                </svg>
              </div>
              {/* Right side: file indicator and status badges */}
              <div className="flex items-center gap-3">
                <CompactFileIndicator
                  isExpanded={isExpanded}
                  hasVideo={hasCompactView}
                  thumbnailUrl={videoInfo?.thumbnailUrl}
                  fileName={fileName}
                  t={t}
                />
              </div>
            </div>
            {/* Collapsible content with smooth animation */}
            <div
              id="input-video-details"
              data-testid="input-video-details"
              aria-hidden={!isExpanded}
              inert={!isExpanded}
              className={`transition-all duration-300 ease-in-out overflow-hidden ${isExpanded ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0"}`}
            >
              <div className="card flex flex-col gap-4 py-3 px-4 animate-fade-in border-emerald-500/20 bg-emerald-500/5 transition-all hover:bg-emerald-500/10 sm:flex-row sm:items-center">
                <SelectedVideoThumbnail
                  thumbnailUrl={videoInfo?.thumbnailUrl}
                  videoUrl={videoUrl}
                  isCompleted={selectedJob?.status === "completed"}
                  t={t}
                />

                {/* File Info */}
                <div className="w-full min-w-0 flex-1">
                  <h4
                    className="text-sm font-semibold text-[var(--foreground)] truncate"
                    title={fileName}
                  >
                    {fileName}
                  </h4>
                  <div className="flex items-center gap-3 text-xs mt-0.5">
                    <p className="text-[var(--muted)] flex items-center gap-1.5">
                      <span>{fileSize} MB</span>
                      <span className="w-1 h-1 rounded-full bg-[var(--border)]" />
                      {isProcessing ? (
                        <span className="text-amber-400 font-medium animate-pulse">
                          {t("statusProcessingEllipsis")}
                        </span>
                      ) : (
                        <span className="text-emerald-500 font-medium">
                          {t("statusReady")}
                        </span>
                      )}
                    </p>

                    {!isProcessing && (
                      <span className="hidden sm:inline-block text-[var(--muted)] opacity-60 text-[10px] uppercase tracking-wider">
                        {t("dragToReplace")}
                      </span>
                    )}
                  </div>
                </div>

                {/* Actions Group */}
                <div className="flex w-full items-center gap-2 sm:w-auto">
                  <ProcessingActionButton
                    isProcessing={isProcessing}
                    selectedFile={selectedFile}
                    selectedJob={selectedJob}
                    transcribeMode={transcribeMode}
                    isVideoValidationPending={isVideoValidationPending}
                    fileValidationError={fileValidationError}
                    selectedCost={selectedCost}
                    onViewResults={() => {
                      setOverrideStep(3);
                      setTimeout(() => {
                        document
                          .getElementById("step-3-wrapper")
                          ?.scrollIntoView({
                            behavior: "smooth",
                            block: "start",
                          });
                      }, 350);
                    }}
                    onStart={handleStart}
                    t={t}
                  />

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onFileSelect(null);
                      onJobSelect(null);
                    }}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg border border-dashed border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--surface-elevated)] hover:text-[var(--foreground)] text-[var(--muted)] transition-all flex items-center gap-2 group/upload"
                    title={t("uploadNew")}
                    aria-label={t("uploadNew")}
                  >
                    <svg
                      className="w-3.5 h-3.5 group-hover/upload:text-[var(--accent)] transition-colors"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
                      />
                    </svg>
                    <span className="hidden sm:inline">{t("uploadNew")}</span>
                  </button>
                </div>
              </div>
              <VideoCreditPricing
                durationSeconds={pricingDuration}
                selectedCost={selectedCost}
                selectedDurationAvailable={selectedDurationAvailable}
                selectedQuoteKey={selectedQuote.key}
              />
            </div>
            {error && (
              <div className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)] animate-fade-in">
                {error}
              </div>
            )}
            <UploadValidationError message={fileValidationError} />

            <ProcessingProgress
              isProcessing={isProcessing}
              progress={progress}
              statusMessage={statusMessage}
              onCancel={onCancelProcessing}
              t={t}
            />
          </div>{" "}
          {/* End collapsible wrapper */}
        </>
      );
    }

    return (
      <div
        id="upload-section"
        data-testid="upload-section"
        className="studio-upload-shell animate-fade-in-up-scale"
      >
        <div
          className={`studio-upload-zone ${isDragOver ? "studio-upload-zone-active" : ""}`}
          data-clickable="true"
          onClick={handleUploadCardClick}
          onKeyDown={(e) => handleKeyDown(e, handleUploadCardClick)}
          role="button"
          tabIndex={0}
          aria-label={t("uploadDropTitle")}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          <HiddenVideoInput
            inputRef={fileInputRef}
            onChange={handleFileChange}
            disabled={isProcessing}
          />

          <div className="studio-upload-preview" aria-hidden="true">
            <svg viewBox="0 0 48 48" fill="none">
              <rect
                x="10"
                y="7"
                width="28"
                height="34"
                rx="5"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <path d="M21 17.5 30 24l-9 6.5v-13Z" fill="currentColor" />
            </svg>
          </div>

          <span className="studio-upload-cta">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {isDragOver ? t("dropFileHere") : t("uploadDropTitle")}
          </span>
          <p>{isDragOver ? t("releaseToUpload") : t("uploadDropSubtitle")}</p>
          <small>
            {t("uploadDropFootnote", {
              size: MAX_UPLOAD_MB,
              duration: MAX_VIDEO_DURATION_LABEL,
            })}
          </small>
        </div>
        <UploadRetentionNote t={t} />
        <UploadValidationError message={fileValidationError} />
      </div>
    );
  }, [
    selectedFile,
    t,
    videoInfo,
    isProcessing,
    error,
    selectedJob,
    handleStart,
    onFileSelect,
    handleKeyDown,
    handleSummaryToggle,
    isDragOver,
    isExpanded,
    handleUploadCardClick,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
    handleDrop,
    fileInputRef,
    handleFileChange,
    fileValidationError,
    videoUrl,
    progress,
    statusMessage,
    onCancelProcessing,
    onJobSelect,
    setOverrideStep,
    transcribeMode,
    isVideoValidationPending,
    fileName,
    fileSize,
    hasCompactView,
    pricingDuration,
    videoPricing,
  ]);
}
