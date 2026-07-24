import React, { useMemo, useState, useCallback, useEffect } from 'react';
import Image from 'next/image';
import { useI18n } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { validateVideoAspectRatio } from '@/lib/video';
import { TokenIcon } from '@/components/icons';
import {
    formatPoints,
    processVideoCostForSelection,
    VIDEO_CREDIT_BRACKETS,
    videoCreditQuoteForDuration,
} from '@/lib/points';
import { resolveTranscriptionTier } from '@/lib/transcription';

const parsedMaxUploadMb = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB ?? '1024');
const MAX_UPLOAD_MB = Number.isFinite(parsedMaxUploadMb) && parsedMaxUploadMb > 0
    ? Math.floor(parsedMaxUploadMb)
    : 1024;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
const parsedMaxVideoDurationSeconds = Number(process.env.NEXT_PUBLIC_MAX_VIDEO_DURATION_SECONDS ?? '600');
const MAX_VIDEO_DURATION_SECONDS = Number.isFinite(parsedMaxVideoDurationSeconds) && parsedMaxVideoDurationSeconds > 0
    ? Math.floor(parsedMaxVideoDurationSeconds)
    : 600;
const MAX_VIDEO_DURATION_LABEL = `${Math.floor(MAX_VIDEO_DURATION_SECONDS / 60)}:${String(MAX_VIDEO_DURATION_SECONDS % 60).padStart(2, '0')}`;
const ALLOWED_VIDEO_EXT = /\.(mp4|mov|mkv)$/i;

function formatVideoDuration(durationSeconds: number): string {
    const roundedSeconds = Math.max(1, Math.ceil(durationSeconds));
    return `${Math.floor(roundedSeconds / 60)}:${String(roundedSeconds % 60).padStart(2, '0')}`;
}

export function UploadSection() {
    const { t } = useI18n();
    const unsupportedTypeError = t('uploadUnsupportedType');
    const oversizedFileError = t('uploadFileTooLarge', { size: MAX_UPLOAD_MB });
    const unreadableDurationError = t('uploadDurationUnreadable');
    const excessiveDurationError = t('uploadDurationTooLong', { duration: MAX_VIDEO_DURATION_LABEL });

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
    const [fileValidationError, setFileValidationError] = useState<string | null>(null);
    // Step 1 starts with a compact summary for an existing file. Step 2 expands
    // the same input summary to show processing controls and progress.
    const [collapsePreference, setCollapsePreference] = useState<{
        step: number;
        collapsed: boolean;
    } | null>(null);
    const validationRequestId = React.useRef(0);

    const localCollapsed = collapsePreference?.step === currentStep
        ? collapsePreference.collapsed
        : currentStep === 1;
    const isExpanded = !localCollapsed || isProcessing;

    const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0] || null;
        setFileValidationError(null);
        if (file) {
            if (!ALLOWED_VIDEO_EXT.test(file.name)) {
                setFileValidationError(unsupportedTypeError);
                return;
            }
            if (file.size > MAX_UPLOAD_BYTES) {
                setFileValidationError(oversizedFileError);
                return;
            }
            onFileSelect(file);
        }
    }, [onFileSelect, oversizedFileError, unsupportedTypeError]);

    const handleUploadCardClick = useCallback(() => {
        if (!isProcessing) {
            fileInputRef.current?.click();
        }
    }, [isProcessing, fileInputRef]);

    const handleKeyDown = useCallback((e: React.KeyboardEvent, callback: () => void) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            callback();
        }
    }, []);

    const handleDragEnter = useCallback((e: React.DragEvent<HTMLDivElement>) => {
        e.preventDefault();
        e.stopPropagation();
        if (!isProcessing) {
            setIsDragOver(true);
        }
    }, [isProcessing]);

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

    const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(false);

        if (isProcessing) return;

        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            const file = files[0];
            setFileValidationError(null);
            if (!ALLOWED_VIDEO_EXT.test(file.name)) {
                setFileValidationError(unsupportedTypeError);
                return;
            }
            if (file.size > MAX_UPLOAD_BYTES) {
                setFileValidationError(oversizedFileError);
                return;
            }
            onFileSelect(file);
            setOverrideStep(null);
        }
    }, [isProcessing, onFileSelect, oversizedFileError, setOverrideStep, unsupportedTypeError]);

    // Effect for validating video when selectedFile changes
    useEffect(() => {
        let isCancelled = false;
        const requestId = ++validationRequestId.current;

        if (!selectedFile) {
            queueMicrotask(() => {
                if (isCancelled || requestId !== validationRequestId.current) return;
                setVideoInfo(null);
                setPreviewVideoUrl(null);
                setCues([]);
                setFileValidationError(null);
            });
            return () => {
                isCancelled = true;
            };
        }

        const blobUrl = URL.createObjectURL(selectedFile);
        queueMicrotask(() => {
            if (isCancelled || requestId !== validationRequestId.current) return;
            setPreviewVideoUrl(blobUrl);
            setCues([]);
            setFileValidationError(null);
        });

        void validateVideoAspectRatio(selectedFile).then(info => {
            if (!isCancelled && requestId === validationRequestId.current) {
                setVideoInfo(info);
                if (info.durationSeconds <= 0) {
                    setFileValidationError(unreadableDurationError);
                } else if (info.durationSeconds > MAX_VIDEO_DURATION_SECONDS) {
                    setFileValidationError(excessiveDurationError);
                }
            }
        });

        return () => {
            isCancelled = true;
            URL.revokeObjectURL(blobUrl);
        };
    }, [excessiveDurationError, selectedFile, setCues, setPreviewVideoUrl, setVideoInfo, unreadableDurationError]);

    const handleSummaryToggle = useCallback(() => {
        if (!isProcessing) {
            setCollapsePreference({ step: currentStep, collapsed: !localCollapsed });
        }
    }, [currentStep, isProcessing, localCollapsed]);

    return useMemo(() => {
        const pricingDuration = videoInfo?.durationSeconds
            ?? selectedJob?.result_data?.duration_seconds
            ?? null;
        const selectedQuote = videoCreditQuoteForDuration(pricingDuration);
        const selectedCost = processVideoCostForSelection(
            transcribeProvider,
            transcribeMode,
            pricingDuration,
        );

        // Show compact view if we have a file OR a completed job (restored state)
        // Check if we have consistent job data to display if file is missing
        // Don't show compact view if the job's files are marked as missing on the server
        const hasJobData = selectedJob?.status === 'completed' &&
            selectedJob.result_data &&
            !selectedJob.result_data.files_missing;

        if (selectedFile || hasJobData || currentStep > 2) {
            const fileName = selectedFile?.name || selectedJob?.result_data?.original_filename || t('processedVideoFallback');
            const fileSize = selectedFile?.size
                ? (selectedFile.size / (1024 * 1024)).toFixed(1)
                : (selectedJob?.result_data?.output_size ? (selectedJob.result_data.output_size / (1024 * 1024)).toFixed(1) : '--');

            return (
                <>
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/mp4,video/quicktime,video/x-matroska"
                        onChange={handleFileChange}
                        className="hidden"
                        disabled={isProcessing}
                    />
                    <div id="upload-section-compact" data-testid="upload-section" className="card space-y-4 scroll-mt-32 animate-fade-in-up-scale">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div
                                role="button"
                                tabIndex={0}
                                aria-expanded={isExpanded}
                                aria-controls="input-video-details"
                                aria-label={t('inputVideoSummaryToggle')}
                                onKeyDown={(e) => handleKeyDown(e, handleSummaryToggle)}
                                className={`flex items-center gap-3 transition-all duration-300 cursor-pointer group/step focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:rounded-full focus-visible:outline-none ${isExpanded ? 'scale-[1.01]' : 'hover:scale-[1.005]'}`}
                                onClick={handleSummaryToggle}
                            >
                                <h3 className="text-xl font-semibold">{t('inputVideoTitle')}</h3>
                                {/* Chevron indicator for expand/collapse */}
                                <svg
                                    className={`w-5 h-5 text-[var(--muted)] transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`}
                                    fill="none"
                                    viewBox="0 0 24 24"
                                    stroke="currentColor"
                                    data-testid="input-video-chevron"
                                    aria-hidden="true"
                                >
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                </svg>
                            </div>
                            {/* Right side: file indicator and status badges */}
                            <div className="flex items-center gap-3">
                                {/* Compact file indicator when collapsed */}
                                {!isExpanded && (selectedFile || hasJobData || currentStep > 2) && (
                                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)] overflow-hidden">
                                        {videoInfo?.thumbnailUrl ? (
                                            <div className="relative w-5 h-5 rounded-full overflow-hidden flex-shrink-0">
                                                <Image
                                                    src={videoInfo.thumbnailUrl}
                                                    alt={t('videoThumbnailAlt')}
                                                    fill
                                                    unoptimized
                                                    className="object-cover"
                                                    sizes="20px"
                                                />
                                            </div>
                                        ) : (
                                            <svg className="w-4 h-4 text-emerald-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                            </svg>
                                        )}
                                        <span className="text-sm font-medium text-[var(--foreground)] truncate max-w-[120px]">{fileName}</span>
                                    </div>
                                )}
                            </div>
                        </div>
                        {/* Collapsible content with smooth animation */}
                        <div
                            id="input-video-details"
                            data-testid="input-video-details"
                            aria-hidden={!isExpanded}
                            inert={!isExpanded}
                            className={`transition-all duration-300 ease-in-out overflow-hidden ${isExpanded ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0'}`}
                        >
                            <div className="card flex flex-col gap-4 py-3 px-4 animate-fade-in border-emerald-500/20 bg-emerald-500/5 transition-all hover:bg-emerald-500/10 sm:flex-row sm:items-center">
                                {/* Thumbnail with Tick Overlay */}
                                <div className="relative h-16 w-16 shrink-0 rounded-lg overflow-hidden bg-black/20 border border-emerald-500/20 group">
                                    {videoInfo?.thumbnailUrl ? (
                                        <Image
                                            src={videoInfo.thumbnailUrl}
                                            alt={t('videoThumbnailAlt')}
                                            fill
                                            unoptimized
                                            className="object-cover opacity-80 transition-opacity group-hover:opacity-100"
                                            sizes="64px"
                                        />
                                    ) : videoUrl ? (
                                        <video
                                            src={videoUrl}
                                            className="w-full h-full object-cover opacity-80 transition-opacity group-hover:opacity-100"
                                            muted
                                            playsInline
                                            loop
                                            onMouseOver={e => e.currentTarget.play().catch(() => { })}
                                            onMouseOut={e => e.currentTarget.pause()}
                                        />
                                    ) : (
                                        <div className="h-full w-full flex items-center justify-center bg-emerald-900/20">
                                            <svg className="w-8 h-8 text-emerald-500/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M15 10l4.553-2.276A1 1 0 0121 8.818v6.364a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                            </svg>
                                        </div>
                                    )}

                                    {/* Centered Green Tick Overlay - Only show when completed */}
                                    {selectedJob?.status === 'completed' && (
                                        <div className="absolute inset-0 flex items-center justify-center">
                                            <div className="w-8 h-8 rounded-full bg-emerald-500/80 shadow-lg shadow-emerald-500/40 flex items-center justify-center text-white transform scale-100 group-hover:scale-110 transition-transform backdrop-blur-[1px]">
                                                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                                </svg>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {/* File Info */}
                                <div className="w-full min-w-0 flex-1">
                                    <h4 className="text-sm font-semibold text-[var(--foreground)] truncate" title={fileName}>
                                        {fileName}
                                    </h4>
                                    <div className="flex items-center gap-3 text-xs mt-0.5">
                                        <p className="text-[var(--muted)] flex items-center gap-1.5">
                                            <span>{fileSize} MB</span>
                                            <span className="w-1 h-1 rounded-full bg-[var(--border)]" />
                                            {isProcessing ? (
                                                <span className="text-amber-400 font-medium animate-pulse">{t('statusProcessingEllipsis')}</span>
                                            ) : (
                                                <span className="text-emerald-500 font-medium">{t('statusReady')}</span>
                                            )}
                                        </p>

                                        {!isProcessing && (
                                            <span className="hidden sm:inline-block text-[var(--muted)] opacity-60 text-[10px] uppercase tracking-wider">
                                                {t('dragToReplace')}
                                            </span>
                                        )}
                                    </div>
                                </div>

                                {/* Actions Group */}
                                <div className="flex w-full items-center gap-2 sm:w-auto">
                                    {/* Action Button Logic */}
                                    {!isProcessing && (
                                        <>
                                            {(() => {
                                                // Check if we have a completed job that matches current tier
                                                const jobCompleted = selectedJob?.status === 'completed';
                                                const jobTier = resolveTranscriptionTier(
                                                    selectedJob?.result_data?.transcribe_tier,
                                                );
                                                const selectedTier = transcribeMode;
                                                const isMatch = Boolean(jobCompleted && jobTier === selectedTier);

                                                if (isMatch) {
                                                    // MATCH: Show "View Results"
                                                    return (
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                setOverrideStep(3);
                                                                // Wait for UploadSection to collapse (300ms)
                                                                setTimeout(() => {
                                                                    document.getElementById('step-3-wrapper')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                                                                }, 350);
                                                            }}
                                                            className="px-4 py-1.5 text-xs font-bold rounded-lg bg-emerald-500 text-white hover:brightness-110 shadow-lg shadow-emerald-500/20 transition-all active:scale-95 flex items-center gap-2"
                                                        >
                                                            <span>{t('viewResults')}</span>
                                                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                                            </svg>
                                                        </button>
                                                    );
                                                } else {
                                                    // MISMATCH or NO JOB: Show "Start Processing"
                                                    // Only show if we selected a file (or have a file selected)
                                                    // If we have a job but it's mismatch, we re-process.
                                                    if (!isProcessing && (selectedFile || selectedJob)) {
                                                        // If selectedJob is present but mismatch, we allow re-processing
                                                        return (
                                                            <button
                                                                disabled={Boolean(fileValidationError)}
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    if (fileValidationError) return;
                                                                    handleStart();
                                                                }}
                                                                className={`group px-5 py-2 text-xs font-bold rounded-lg transition-all active:scale-95 flex items-center gap-2 ${fileValidationError
                                                                    ? 'bg-[var(--border)] text-[var(--muted)] cursor-not-allowed'
                                                                    : 'bg-[var(--accent)] text-[var(--background)] hover:brightness-110 shadow-lg shadow-[var(--accent)]/20'
                                                                    }`}
                                                            >
                                                                <span>{t('startProcessing')}</span>
                                                                <div className="flex items-center gap-1.5 opacity-80 border-l border-current/20 pl-2 ml-0.5">
                                                                    <TokenIcon className="w-3.5 h-3.5" />
                                                                    <span className="font-mono">{formatPoints(selectedCost)}</span>
                                                                </div>
                                                            </button>
                                                        );
                                                    }
                                                }
                                            })()}
                                        </>
                                    )}

                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onFileSelect(null);
                                            onJobSelect(null);
                                        }}
                                        className="px-3 py-1.5 text-xs font-medium rounded-lg border border-dashed border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--surface-elevated)] hover:text-[var(--foreground)] text-[var(--muted)] transition-all flex items-center gap-2 group/upload"
                                        title={t('uploadNew')}
                                        aria-label={t('uploadNew')}
                                    >
                                        <svg className="w-3.5 h-3.5 group-hover/upload:text-[var(--accent)] transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                                        </svg>
                                        <span className="hidden sm:inline">{t('uploadNew')}</span>
                                    </button>
                                </div>
                            </div>
                            <div
                                data-testid="video-credit-pricing"
                                className="rounded-2xl border border-sky-400/20 bg-sky-400/[0.045] p-4"
                            >
                                <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                                    <div>
                                        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-sky-500">
                                            {t('videoCreditPricingKicker')}
                                        </p>
                                        <p className="mt-1 text-sm text-[var(--muted)]">
                                            {pricingDuration
                                                ? t('videoCreditPricingDuration', {
                                                    duration: formatVideoDuration(pricingDuration),
                                                })
                                                : t('videoCreditPricingPending')}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-2 text-sm font-bold text-sky-500">
                                        <TokenIcon className="h-4 w-4" />
                                        <span>{formatPoints(selectedCost)} {t('creditsLabel')}</span>
                                    </div>
                                </div>
                                <div className="grid grid-cols-3 gap-2" aria-label={t('videoCreditPricingTiers')}>
                                    {VIDEO_CREDIT_BRACKETS.map((quote) => {
                                        const isActive = quote.key === selectedQuote.key;
                                        return (
                                            <div
                                                key={quote.key}
                                                data-active={isActive ? 'true' : 'false'}
                                                className={`rounded-xl border px-2 py-3 text-center transition ${
                                                    isActive
                                                        ? 'border-sky-400 bg-sky-400/10 text-[var(--foreground)] shadow-[0_0_0_1px_rgba(56,189,248,0.12)]'
                                                        : 'border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--muted)]'
                                                }`}
                                            >
                                                <span className="block text-[10px] font-semibold uppercase tracking-wide">
                                                    {t('videoCreditPricingUpTo', {
                                                        minutes: quote.maxDurationSeconds / 60,
                                                    })}
                                                </span>
                                                <strong className="mt-1 block text-sm">
                                                    {formatPoints(quote.credits)} {t('creditsLabel')}
                                                </strong>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        </div>
                        {error && (
                            <div className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)] animate-fade-in">
                                {error}
                            </div>
                        )}
                        {fileValidationError && (
                            <div className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)] animate-fade-in">
                                {fileValidationError}
                            </div>
                        )}

                        {/* PROCESSING STATE: Progress Bar */}
                        {isProcessing && (
                            <div
                                role="progressbar"
                                aria-valuenow={progress}
                                aria-valuemin={0}
                                aria-valuemax={100}
                                aria-labelledby="progress-label"
                                className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 space-y-3 animate-fade-in mt-4"
                            >
                                <div className="flex items-center justify-between text-sm">
                                    <span id="progress-label" className="font-medium">{statusMessage || t('progressLabel')}</span>
                                    <span className="text-[var(--accent)] font-semibold">{progress}%</span>
                                </div>
                                <progress
                                    className="upload-progress"
                                    value={progress}
                                    max={100}
                                    aria-hidden="true"
                                    tabIndex={-1}
                                />
                                {onCancelProcessing && (
                                    <div className="flex justify-end pt-1">
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onCancelProcessing();
                                            }}
                                            className="px-4 py-1.5 rounded-lg text-sm font-medium bg-[var(--danger)]/10 text-[var(--danger)] hover:bg-[var(--danger)]/20 border border-[var(--danger)]/30 transition-colors"
                                        >
                                            {t('cancelProcessing')}
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}
                    </div > {/* End collapsible wrapper */}
                </>
            );
        }

        return (
            <div id="upload-section" data-testid="upload-section" className="studio-upload-shell animate-fade-in-up-scale">
                <div
                    className={`studio-upload-zone ${isDragOver ? 'studio-upload-zone-active' : ''}`}
                    data-clickable="true"
                    onClick={handleUploadCardClick}
                    onKeyDown={(e) => handleKeyDown(e, handleUploadCardClick)}
                    role="button"
                    tabIndex={0}
                    aria-label={t('uploadDropTitle')}
                    onDragEnter={handleDragEnter}
                    onDragLeave={handleDragLeave}
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                >
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/mp4,video/quicktime,video/x-matroska"
                        onChange={handleFileChange}
                        className="hidden"
                        disabled={isProcessing}
                    />

                    <div className="studio-upload-preview" aria-hidden="true">
                        <svg viewBox="0 0 48 48" fill="none">
                            <rect x="10" y="7" width="28" height="34" rx="5" stroke="currentColor" strokeWidth="1.5" />
                            <path d="M21 17.5 30 24l-9 6.5v-13Z" fill="currentColor" />
                        </svg>
                    </div>

                    <span className="studio-upload-cta">
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        {isDragOver ? t('dropFileHere') : t('uploadDropTitle')}
                    </span>
                    <p>{isDragOver ? t('releaseToUpload') : t('uploadDropSubtitle')}</p>
                    <small>{t('uploadDropFootnote', { duration: MAX_VIDEO_DURATION_LABEL })}</small>
                </div>

                {fileValidationError && (
                    <div className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)] animate-fade-in">
                        {fileValidationError}
                    </div>
                )}
            </div>
        );
    }, [
        selectedFile, t, currentStep, videoInfo, isProcessing, error,
        selectedJob, handleStart, onFileSelect, handleKeyDown,
        handleSummaryToggle, isDragOver,
        isExpanded,
        handleUploadCardClick, handleDragEnter, handleDragLeave, handleDragOver,
        handleDrop, fileInputRef, handleFileChange, fileValidationError, videoUrl, progress, statusMessage, onCancelProcessing,
        onJobSelect, setOverrideStep, transcribeMode, transcribeProvider
    ]);
}
