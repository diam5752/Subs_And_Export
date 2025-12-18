import React, { useMemo, useState, useCallback, useEffect } from 'react';
import Image from 'next/image';
import { useI18n } from '@/context/I18nContext';
import { useAppEnv } from '@/context/AppEnvContext';
import { useProcessContext } from '../ProcessContext';
import { api } from '@/lib/api';
import { validateVideoAspectRatio } from '@/lib/video';
import { formatPoints, processVideoCostForSelection } from '@/lib/points';

const MAX_UPLOAD_BYTES = 1024 * 1024 * 1024; // 1GiB
const MAX_VIDEO_DURATION_SECONDS = 3 * 60;
const ALLOWED_VIDEO_EXT = /\.(mp4|mov|mkv)$/i;

export function UploadSection() {
    const { t } = useI18n();
    const { appEnv } = useAppEnv();
    const showDevTools = appEnv === 'dev';

    const {
        selectedFile,
        onFileSelect,
        isProcessing,
        hasChosenModel,
        transcribeProvider,
        transcribeMode,
        AVAILABLE_MODELS,
        currentStep,
        setOverrideStep,
        setHasChosenModel,
        onJobSelect,
        handleStart,
        fileInputRef,
        resultsRef,
        videoInfo,
        setVideoInfo,
        setPreviewVideoUrl,
        setCues,
        selectedJob,
        error,
        progress,
        statusMessage,
        onCancelProcessing,
        videoUrl
    } = useProcessContext();

    const [isDragOver, setIsDragOver] = useState(false);
    const [devSampleLoading, setDevSampleLoading] = useState(false);
    const [devSampleError, setDevSampleError] = useState<string | null>(null);
    const [fileValidationError, setFileValidationError] = useState<string | null>(null);
    const [pendingAutoStart, setPendingAutoStart] = useState(false);
    const validationRequestId = React.useRef(0);

    const activeTheme = useMemo(() => {
        if (transcribeProvider === 'groq') {
            if (transcribeMode === 'enhanced') {
                return {
                    borderColor: 'border-emerald-500/50',
                    bgGradient: 'from-emerald-500/20 via-transparent to-emerald-500/5',
                    iconColor: 'text-emerald-400',
                    glowColor: 'shadow-[0_0_30px_-5px_rgba(52,211,153,0.3)]'
                };
            }
            // Default to Ultimate (Purple)
            return {
                borderColor: 'border-purple-500/50',
                bgGradient: 'from-purple-500/20 via-transparent to-purple-500/5',
                iconColor: 'text-purple-400',
                glowColor: 'shadow-[0_0_30px_-5px_rgba(168,85,247,0.3)]'
            };
        }
        if (transcribeProvider === 'whispercpp') return {
            borderColor: 'border-cyan-500/50',
            bgGradient: 'from-cyan-500/20 via-transparent to-cyan-500/5',
            iconColor: 'text-cyan-400',
            glowColor: 'shadow-[0_0_30px_-5px_rgba(6,182,212,0.3)]'
        };
        return {
            borderColor: 'border-[var(--accent)]/50',
            bgGradient: 'from-[var(--accent)]/20 via-transparent to-[var(--accent-secondary)]/10',
            iconColor: 'text-[var(--accent)]',
            glowColor: 'shadow-[0_0_30px_-5px_rgba(141,247,223,0.3)]'
        };
    }, [transcribeProvider, transcribeMode]);

    const selectedModel = useMemo(() =>
        AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode),
        [AVAILABLE_MODELS, transcribeProvider, transcribeMode]);

    const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0] || null;
        setFileValidationError(null);
        if (file) {
            if (!ALLOWED_VIDEO_EXT.test(file.name)) {
                setFileValidationError('Unsupported file type. Please upload an MP4, MOV, or MKV video.');
                return;
            }
            if (file.size > MAX_UPLOAD_BYTES) {
                setFileValidationError('File too large. Maximum allowed size is 1GB.');
                return;
            }
            setPendingAutoStart(true);
            onFileSelect(file);
        }
    }, [onFileSelect]);

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
                setFileValidationError('Unsupported file type. Please upload an MP4, MOV, or MKV video.');
                return;
            }
            if (file.size > MAX_UPLOAD_BYTES) {
                setFileValidationError('File too large. Maximum allowed size is 1GB.');
                return;
            }
            setPendingAutoStart(true);
            onFileSelect(file);
            setOverrideStep(null);
        }
    }, [isProcessing, onFileSelect, setOverrideStep]);

    const handleLoadDevSample = useCallback(
        async (event: React.MouseEvent<HTMLButtonElement>) => {
            event.stopPropagation();
            if (isProcessing || devSampleLoading) return;

            setDevSampleError(null);
            setDevSampleLoading(true);

            try {
                if (fileInputRef.current) {
                    fileInputRef.current.value = '';
                }

                // We do NOT want to full reset because it might flicker
                // But we should ensure we are clean.
                // onReset(); // Removed full reset to avoid state fighting

                // Instead just clear file and job if needed, but we are overwriting anyway.
                onFileSelect(null);

                // Map mode to model_size (logic copied from ProcessProvider)
                const modelMap: Record<string, string> = {
                    fast: 'tiny',
                    balanced: 'medium',
                    turbo: 'turbo',
                    best: 'large-v3',
                };
                const safeMode = transcribeMode || 'turbo';
                const modelSize = modelMap[safeMode] || 'turbo';
                const safeProvider = transcribeProvider || 'local';

                const job = await api.loadDevSampleJob(safeProvider, modelSize);

                // IMPORTANT: Ensure UI enters "Model Chosen" state so Step 2/3 are visible
                setHasChosenModel(true);
                onJobSelect(job);

                // Wait for render cycle
                setTimeout(() => {
                    resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 100);

            } catch (err: unknown) {
                console.error('Failed to load dev sample:', err);
                let msg = 'Failed to load sample';
                if (err instanceof Error) msg = err.message;
                // Extract detail from backend error if available
                const responseDetail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
                if (typeof responseDetail === 'string' && responseDetail.trim()) {
                    msg = responseDetail;
                }
                setDevSampleError(msg);
                // Also show in main error for visibility
                // setVideoInfo(null); // Clear video info if failed
            } finally {
                setDevSampleLoading(false);
            }
        },
        [isProcessing, devSampleLoading, fileInputRef, onFileSelect, setHasChosenModel, onJobSelect, resultsRef, transcribeMode, transcribeProvider]
    );

    // Effect for validating video when selectedFile changes
    useEffect(() => {
        let isCancelled = false;

        if (!selectedFile) {
            validationRequestId.current += 1;
            setVideoInfo(null);
            setPreviewVideoUrl(null);
            setCues([]);
            setFileValidationError(null);
            return;
        }

        const requestId = ++validationRequestId.current;

        const blobUrl = URL.createObjectURL(selectedFile);
        setPreviewVideoUrl(blobUrl);
        setCues([]);

        validateVideoAspectRatio(selectedFile).then(info => {
            if (!isCancelled && requestId === validationRequestId.current) {
                setVideoInfo(info);
                if (info.durationSeconds <= 0) {
                    setFileValidationError('Could not read video duration. Please try another file.');
                    setPendingAutoStart(false);
                } else if (info.durationSeconds > MAX_VIDEO_DURATION_SECONDS) {
                    setFileValidationError('Video too long. Maximum allowed duration is 3 minutes.');
                    setPendingAutoStart(false);
                }
            }
        });

        return () => {
            isCancelled = true;
            URL.revokeObjectURL(blobUrl);
        };
    }, [selectedFile, setCues, setPreviewVideoUrl, setVideoInfo]);

    // Auto-start processing when file is selected AND pendingAutoStart is true
    useEffect(() => {
        if (pendingAutoStart && selectedFile && videoInfo && !fileValidationError && !isProcessing && !selectedJob && hasChosenModel) {
            setPendingAutoStart(false);
            handleStart();
        }
    }, [pendingAutoStart, selectedFile, videoInfo, fileValidationError, isProcessing, selectedJob, hasChosenModel, handleStart]);

    const handleStepClick = useCallback((id: string) => {
        setOverrideStep(2);
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, [setOverrideStep]);

    return useMemo(() => {
        const selectedCost = selectedModel
            ? processVideoCostForSelection(selectedModel.provider as string, selectedModel.mode as string)
            : processVideoCostForSelection(transcribeProvider, transcribeMode);

        // Show compact view if we have a file OR a completed job (restored state)
        // Check if we have consistent job data to display if file is missing
        const hasJobData = selectedJob?.status === 'completed' && selectedJob.result_data;

        if (selectedFile || hasJobData) {
            const fileName = selectedFile?.name || selectedJob?.result_data?.original_filename || 'Processed Video';
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
                    <div id="upload-section-compact" className="space-y-4 scroll-mt-32 animate-fade-in-up-scale">
                        <div
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => handleKeyDown(e, () => handleStepClick('upload-section-compact'))}
                            className={`mb-2 flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 2 ? 'opacity-40 grayscale blur-[1px] hover:opacity-80 hover:grayscale-0 hover:blur-0' : 'opacity-100 scale-[1.01]'}`}
                            onClick={() => handleStepClick('upload-section-compact')}
                        >
                            <span className={`flex items-center justify-center px-4 py-1.5 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 ${currentStep === 2
                                ? 'bg-[var(--accent)] border-[var(--accent)] text-white shadow-[0_0_20px_2px_var(--accent)] scale-105 ring-2 ring-[var(--accent)]/30'
                                : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)] group-hover/step:border-[var(--accent)]/50 group-hover/step:text-[var(--accent)]'
                                }`}>STEP 2</span>
                            <h3 className="text-xl font-semibold">Upload Video</h3>
                        </div>
                        <div className="card flex items-center gap-4 py-3 px-4 animate-fade-in border-emerald-500/20 bg-emerald-500/5 transition-all hover:bg-emerald-500/10">
                            {/* Thumbnail with Tick Overlay */}
                            <div className="relative h-16 w-16 shrink-0 rounded-lg overflow-hidden bg-black/20 border border-emerald-500/20 group">
                                {videoInfo?.thumbnailUrl ? (
                                    <Image
                                        src={videoInfo.thumbnailUrl}
                                        alt="Thumbnail"
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
                            <div className="flex-1 min-w-0">
                                <h4 className="text-sm font-semibold text-[var(--foreground)] truncate" title={fileName}>
                                    {fileName}
                                </h4>
                                <div className="flex items-center gap-3 text-xs mt-0.5">
                                    <p className="text-[var(--muted)] flex items-center gap-1.5">
                                        <span>{fileSize} MB</span>
                                        <span className="w-1 h-1 rounded-full bg-[var(--border)]" />
                                        {isProcessing ? (
                                            <span className="text-amber-400 font-medium animate-pulse">Processing...</span>
                                        ) : (
                                            <span className="text-emerald-500 font-medium">Ready</span>
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
                            <div className="flex items-center gap-2">
                                {/* Action Button Logic */}
                                {!isProcessing && (
                                    <>
                                        {(() => {
                                            // Check if we have a completed job that matches current provider
                                            const jobCompleted = selectedJob?.status === 'completed';
                                            const jobProvider = selectedJob?.result_data?.transcribe_provider;
                                            const jobModel = selectedJob?.result_data?.model_size;

                                            let isMatch = jobCompleted && jobProvider === transcribeProvider;

                                            // Strict check for Groq models
                                            if (isMatch && jobProvider === 'groq') {
                                                const isEnhancedJob = jobModel === 'enhanced' || (jobModel && jobModel.includes('turbo'));
                                                const isUltimateJob = jobModel === 'ultimate' || (jobModel && !jobModel.includes('turbo') && !jobModel.includes('enhanced'));

                                                if (transcribeMode === 'enhanced') {
                                                    isMatch = Boolean(isEnhancedJob);
                                                } else if (transcribeMode === 'ultimate') {
                                                    isMatch = Boolean(isUltimateJob);
                                                }
                                            }

                                            if (isMatch) {
                                                // MATCH: Show "View Results"
                                                return (
                                                    <button
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            setOverrideStep(3);
                                                            document.getElementById('preview-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                                                        }}
                                                        className="px-4 py-1.5 text-xs font-bold rounded-lg bg-emerald-500 text-white hover:brightness-110 shadow-lg shadow-emerald-500/20 transition-all active:scale-95 flex items-center gap-2"
                                                    >
                                                        <span>View Results</span>
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
                                                    className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all active:scale-95 ${
                                                        fileValidationError
                                                            ? 'bg-[var(--border)] text-[var(--muted)] cursor-not-allowed'
                                                            : 'bg-[var(--accent)] text-[var(--background)] hover:brightness-110 shadow-lg shadow-[var(--accent)]/20'
                                                    }`}
                                                >
                                                    {t('startProcessing')} · {formatPoints(selectedCost)}
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
                                        setHasChosenModel(true);
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
                        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 space-y-3 animate-fade-in mt-4">
                            <div className="flex items-center justify-between text-sm">
                                <span className="font-medium">{statusMessage || t('progressLabel')}</span>
                                <span className="text-[var(--accent)] font-semibold">{progress}%</span>
                            </div>
                            <div className="w-full bg-[var(--surface)] rounded-full h-2 overflow-hidden">
                                <div
                                    className="progress-bar bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] h-2 rounded-full"
                                    style={{ width: `${progress}%` }}
                                />
                            </div>
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
                </>
            );
        }

        return (
            <div id="upload-section" className={`space-y-4 scroll-mt-32 animate-fade-in-up-scale transition-opacity duration-300 ${!hasChosenModel ? 'opacity-40 pointer-events-none' : ''}`}>
                <div
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => handleKeyDown(e, () => handleStepClick('upload-section'))}
                    className={`mb-2 flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 2 ? 'opacity-40 grayscale blur-[1px] hover:opacity-80 hover:grayscale-0 hover:blur-0' : 'opacity-100 scale-[1.01]'}`}
                    onClick={() => handleStepClick('upload-section')}
                >
                    <span className={`flex items-center justify-center px-4 py-1.5 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 ${currentStep === 2
                        ? 'bg-[var(--accent)] border-[var(--accent)] text-white shadow-[0_0_20px_2px_var(--accent)] scale-105 ring-2 ring-[var(--accent)]/30'
                        : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)] group-hover/step:border-[var(--accent)]/50 group-hover/step:text-[var(--accent)]'
                        }`}>STEP 2</span>
                    <h3 className="text-xl font-semibold">Upload Video</h3>
                </div>
                {!hasChosenModel && (
                    <p className="text-xs text-[var(--muted)] mt-1 italic">Select a model above to unlock</p>
                )}

                <div
                    className={`card relative overflow-hidden cursor-pointer group transition-all duration-500 ${isDragOver
                        ? `border-2 border-dashed bg-opacity-10 scale-[1.02] ${activeTheme.borderColor}`
                        : `border-2 ${activeTheme.borderColor} ${activeTheme.glowColor}`
                        } ${!hasChosenModel ? 'grayscale' : ''}`}
                    data-clickable="true"
                    onClick={handleUploadCardClick}
                    onKeyDown={(e) => handleKeyDown(e, handleUploadCardClick)}
                    role="button"
                    tabIndex={0}
                    aria-label={selectedFile ? t('changeFile') || 'Change file' : t('uploadDropTitle')}
                    onDragEnter={handleDragEnter}
                    onDragLeave={handleDragLeave}
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                >
                    <div className={`absolute inset-0 transition-opacity pointer-events-none duration-500 ${isDragOver
                        ? `opacity-100 bg-gradient-to-br ${activeTheme.bgGradient}`
                        : `opacity-30 group-hover:opacity-100 bg-gradient-to-br ${activeTheme.bgGradient}`
                        } `} />
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/mp4,video/quicktime,video/x-matroska"
                        onChange={handleFileChange}
                        className="hidden"
                        disabled={isProcessing}
                    />
                    {isDragOver ? (
                        <div className="text-center py-12 relative flex flex-col items-center">
                            <div className="relative">
                                <div className={`mb-3 animate-bounce p-4 rounded-full bg-white/5 ${activeTheme.iconColor}`}>
                                    <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                    </svg>
                                </div>
                                {hasChosenModel && selectedModel && (
                                    <div className={`absolute -bottom-1 -right-1 w-8 h-8 rounded-full border border-[var(--background)] bg-[var(--card-bg)] flex items-center justify-center shadow-lg ${activeTheme.iconColor} animate-pulse`}>
                                        <div className="scale-75">
                                            {selectedModel.icon(true)}
                                        </div>
                                    </div>
                                )}
                            </div>
                            <p className={`text-2xl font-semibold mb-1 ${activeTheme.iconColor}`}>{t('dropFileHere')}</p>
                            <p className="text-[var(--muted)]">{t('releaseToUpload')}</p>
                        </div>
                    ) : (
                        <div className="text-center py-12 relative flex flex-col items-center">
                            <div className="relative">
                                <div className={`mb-3 transition-all duration-500 p-4 rounded-full bg-white/5 ${activeTheme.iconColor} opacity-90`}>
                                    <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                                    </svg>
                                </div>
                                {hasChosenModel && selectedModel && (
                                    <div className={`absolute -bottom-0 -right-0 w-8 h-8 rounded-full border-2 border-[var(--background)] bg-[var(--card-bg)] flex items-center justify-center shadow-lg ${activeTheme.iconColor}`}>
                                        <div className="scale-75">
                                            {selectedModel.icon(true)}
                                        </div>
                                    </div>
                                )}
                            </div>
                            <p className={`text-2xl font-semibold mb-1 transition-colors duration-500 ${activeTheme.iconColor}`}>{t('uploadDropTitle')}</p>
                            <p className="text-[var(--muted)]">{t('uploadDropSubtitle')}</p>
                            <p className="text-xs text-[var(--muted)] mt-4">{t('uploadDropFootnote')}</p>
                        </div>
                    )}
                </div>
                {showDevTools && (
                    <div
                        className={`card relative overflow-hidden border border-[var(--accent)]/35 ${!hasChosenModel ? 'grayscale' : ''}`}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="absolute inset-0 bg-gradient-to-br from-[var(--accent)]/12 via-transparent to-[var(--accent-secondary)]/10 pointer-events-none" />
                        <div className="relative space-y-3">
                            <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)]/60 bg-[var(--surface-elevated)]/70 px-3 py-1 text-[10px] font-semibold tracking-[0.26em] text-[var(--muted)]">
                                <span className="h-2 w-2 rounded-full bg-[var(--accent)]" />
                                DEV TOOLS
                            </div>
                            <div>
                                <h3 className="text-lg font-semibold">Test upload</h3>
                                <p className="text-sm text-[var(--muted)]">
                                    Load an existing processed video so you can preview/export without uploading & transcribing again.
                                </p>
                            </div>
                            <button
                                type="button"
                                className="btn-primary w-full"
                                onClick={handleLoadDevSample}
                                disabled={isProcessing || devSampleLoading}
                            >
                                {devSampleLoading ? 'Loading sample…' : 'Load sample video'}
                            </button>
                            {devSampleError && (
                                <p className="text-xs text-[var(--danger)]">{devSampleError}</p>
                            )}
                        </div>
                    </div>
                )}
            </div>
        );
    }, [
        selectedFile, t, currentStep, videoInfo, isProcessing, error, hasChosenModel,
        selectedJob, handleStart, onFileSelect, setHasChosenModel, handleKeyDown,
        handleStepClick, activeTheme, isDragOver, selectedModel, showDevTools,
        transcribeProvider, transcribeMode,
        handleUploadCardClick, handleDragEnter, handleDragLeave, handleDragOver,
        handleDrop, fileInputRef, handleLoadDevSample, devSampleLoading,
        devSampleError, handleFileChange, fileValidationError, videoUrl, progress, statusMessage, onCancelProcessing
    ]);
}
