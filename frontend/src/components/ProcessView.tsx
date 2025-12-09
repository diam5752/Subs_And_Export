import React, { useEffect, useRef, useState } from 'react';
import { api, JobResponse } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { VideoModal } from './VideoModal';
import { ViralIntelligence } from './ViralIntelligence';

type TranscribeMode = 'fast' | 'balanced' | 'turbo' | 'best';
type TranscribeProvider = 'local' | 'openai';

interface ProcessViewProps {
    selectedFile: File | null;
    onFileSelect: (file: File | null) => void;
    isProcessing: boolean;
    progress: number;
    statusMessage: string;
    error: string;
    onStartProcessing: (options: ProcessingOptions) => Promise<void>;
    onReset: () => void;
    selectedJob: JobResponse | null;
    onJobSelect: (job: JobResponse | null) => void;
    recentJobs: JobResponse[];
    jobsLoading: boolean;
    statusStyles: Record<string, string>;
    formatDate: (ts: string | number) => string;
    buildStaticUrl: (path?: string | null) => string | null;
    onRefreshJobs: () => Promise<void>;
}

export interface ProcessingOptions {
    transcribeMode: TranscribeMode;
    transcribeProvider: TranscribeProvider;
    outputQuality: 'low size' | 'balanced' | 'high quality';
    outputResolution: '1080x1920' | '2160x3840';
    useAI: boolean;
    contextPrompt: string;
}

const parseResolutionString = (resolution?: string | null): { width: number; height: number } | null => {
    if (!resolution) return null;
    const match = resolution.match(/(\d+)\s*[x×]\s*(\d+)/i);
    if (!match) return null;
    const width = Number(match[1]);
    const height = Number(match[2]);
    if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
    return { width, height };
};

const describeResolution = (width?: number, height?: number): { text: string; label: string } | null => {
    if (!width || !height) return null;
    const verticalLines = Math.min(width, height);
    let label = 'SD';
    if (verticalLines >= 2160) {
        label = '4K / 2160p';
    } else if (verticalLines >= 1440) {
        label = 'QHD / 1440p';
    } else if (verticalLines >= 1080) {
        label = 'Full HD / 1080p';
    } else if (verticalLines >= 720) {
        label = 'HD / 720p';
    }
    return { text: `${width}×${height}`, label };
};

const describeResolutionString = (resolution?: string | null): { text: string; label: string } | null => {
    const parsed = parseResolutionString(resolution);
    if (!parsed) return null;
    return describeResolution(parsed.width, parsed.height);
};

export function ProcessView({
    selectedFile,
    onFileSelect,
    isProcessing,
    progress,
    statusMessage,
    error,
    onStartProcessing,
    onReset,
    selectedJob,
    onJobSelect,
    recentJobs,
    jobsLoading,
    statusStyles,
    formatDate,
    buildStaticUrl,
    onRefreshJobs,
}: ProcessViewProps) {
    const { t } = useI18n();
    const fileInputRef = useRef<HTMLInputElement>(null);
    const validationRequestId = useRef(0);

    // Local state for options
    const [showPreview, setShowPreview] = useState(false);
    const [showSettings, setShowSettings] = useState(true);
    const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
    const [transcribeMode, setTranscribeMode] = useState<TranscribeMode>('turbo');
    const [transcribeProvider, setTranscribeProvider] = useState<TranscribeProvider>('local');
    const [outputQuality, setOutputQuality] = useState<'low size' | 'balanced' | 'high quality'>('balanced');
    const [outputResolutionChoice, setOutputResolutionChoice] = useState<'1080x1920' | '2160x3840'>('1080x1920');
    const [useAI, setUseAI] = useState(false);
    const [contextPrompt, setContextPrompt] = useState('');
    const [videoInfo, setVideoInfo] = useState<{ width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null } | null>(null);
    const [isDownloading, setIsDownloading] = useState(false);
    const [outputResolutionInfo, setOutputResolutionInfo] = useState<{ text: string; label: string } | null>(null);

    // Validate video aspect ratio (9:16 for vertical content) and generate thumbnail
    const validateVideoAspectRatio = (file: File): Promise<{ width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null }> => {
        return new Promise((resolve) => {
            const video = document.createElement('video');
            const objectUrl = URL.createObjectURL(file);
            let resolved = false;
            let fallbackTimeout: number | undefined;

            video.preload = 'auto';
            video.muted = true;
            video.playsInline = true;

            const cleanup = () => {
                if (fallbackTimeout) {
                    window.clearTimeout(fallbackTimeout);
                }
                URL.revokeObjectURL(objectUrl);
                video.removeAttribute('src');
                video.load();
            };

            const finish = (thumbnailUrl: string | null) => {
                if (resolved) return;
                resolved = true;
                const width = video.videoWidth || 0;
                const height = video.videoHeight || 0;
                const ratio = width && height ? width / height : 0;
                const is916 = ratio >= 0.5 && ratio <= 0.625;
                cleanup();
                resolve({ width, height, aspectWarning: !is916, thumbnailUrl });
            };

            const captureFrame = () => {
                if (resolved) return;
                if (!video.videoWidth || !video.videoHeight) {
                    finish(null);
                    return;
                }
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext('2d');
                if (!ctx) {
                    finish(null);
                    return;
                }
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                finish(canvas.toDataURL('image/jpeg', 0.7));
            };

            video.addEventListener(
                'loadedmetadata',
                () => {
                    const duration = Number.isFinite(video.duration) ? video.duration : 0;
                    const targetTime = duration > 1 ? Math.min(0.5, duration - 0.1) : 0;
                    // Fallback in case the seek never resolves
                    fallbackTimeout = window.setTimeout(() => captureFrame(), 1200);
                    try {
                        video.currentTime = targetTime;
                    } catch {
                        captureFrame();
                    }
                },
                { once: true }
            );

            video.addEventListener('seeked', captureFrame, { once: true });
            video.addEventListener(
                'error',
                () => {
                    finish(null);
                },
                { once: true }
            );

            video.src = objectUrl;
            video.load();
        });
    };

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0] || null;
        const requestId = ++validationRequestId.current;
        if (file) {
            const info = await validateVideoAspectRatio(file);
            if (requestId === validationRequestId.current) {
                setVideoInfo(info);
            }
        } else {
            setVideoInfo(null);
        }
        onFileSelect(file);
    };

    useEffect(() => {
        if (!selectedFile) {
            validationRequestId.current += 1;
            setVideoInfo(null);
        }
    }, [selectedFile]);

    const handleResetSelection = () => {
        validationRequestId.current += 1;
        setVideoInfo(null);
        setOutputResolutionChoice('1080x1920');
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
        onReset();
    };

    // Instant download handler - forces download instead of opening in browser
    const handleDownload = async (url: string, filename: string) => {
        setIsDownloading(true);
        try {
            const response = await fetch(url);
            const blob = await response.blob();
            const blobUrl = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = blobUrl;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(blobUrl);
        } catch (err) {
            console.error('Download failed:', err);
            // Fallback: open in new tab
            window.open(url, '_blank');
        } finally {
            setIsDownloading(false);
        }
    };

    const handleStart = () => {
        setShowPreview(false); // Hide any previous preview
        onStartProcessing({
            transcribeMode,
            transcribeProvider,
            outputQuality,
            outputResolution: outputResolutionChoice,
            useAI,
            contextPrompt,
        });
    };

    const videoUrl = buildStaticUrl(selectedJob?.result_data?.public_url || selectedJob?.result_data?.video_path);
    const artifactUrl = buildStaticUrl(selectedJob?.result_data?.artifact_url || selectedJob?.result_data?.artifacts_dir);
    const uploadResolution = videoInfo ? describeResolution(videoInfo.width, videoInfo.height) : null;
    const jobResolution = describeResolutionString(selectedJob?.result_data?.resolution);
    const displayResolution = jobResolution || outputResolutionInfo || uploadResolution;

    // Derive resolution from processed video metadata if API did not provide it
    useEffect(() => {
        setOutputResolutionInfo(null);
        if (!videoUrl) return;

        let cancelled = false;
        const video = document.createElement('video');
        video.preload = 'metadata';

        const cleanup = () => {
            video.removeAttribute('src');
        };

        video.addEventListener(
            'loadedmetadata',
            () => {
                if (cancelled) return;
                const info = describeResolution(video.videoWidth, video.videoHeight);
                if (info) {
                    setOutputResolutionInfo(info);
                }
                cleanup();
            },
            { once: true }
        );

        video.addEventListener(
            'error',
            () => {
                cleanup();
            },
            { once: true }
        );

        video.src = videoUrl;

        return () => {
            cancelled = true;
            cleanup();
        };
    }, [videoUrl]);

    return (
        <div className="grid xl:grid-cols-[1.05fr,0.95fr] gap-6">
            <div className="space-y-4">
                {/* Upload Card */}
                <div
                    className="card relative overflow-hidden cursor-pointer group transition-all hover:border-[var(--accent)]/60"
                    data-clickable="true"
                    onClick={() => !isProcessing && fileInputRef.current?.click()}
                >
                    <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity bg-gradient-to-br from-[var(--accent)]/5 via-transparent to-[var(--accent-secondary)]/10 pointer-events-none" />
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/mp4,video/quicktime,video/x-matroska"
                        onChange={handleFileChange}
                        className="hidden"
                        disabled={isProcessing}
                    />
                    {selectedFile ? (

                        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between relative">
                            <div className="flex items-start gap-3">
                                {/* Video Thumbnail */}
                                {videoInfo?.thumbnailUrl ? (
                                    <div className="w-16 h-16 rounded-lg overflow-hidden bg-black/40 flex-shrink-0">
                                        <img
                                            src={videoInfo.thumbnailUrl}
                                            alt="Video thumbnail"
                                            className="w-full h-full object-cover"
                                        />
                                    </div>
                                ) : (
                                    <div className="text-4xl">🎥</div>
                                )}
                                <div>
                                    <p className="text-xl font-semibold break-words [overflow-wrap:anywhere]">{selectedFile.name}</p>
                                    <p className="text-[var(--muted)] mt-1">
                                        {(selectedFile.size / (1024 * 1024)).toFixed(1)} MB · {selectedFile.name.split('.').pop()?.toUpperCase() || 'VIDEO'}
                                        {uploadResolution && (
                                            <span className="ml-2">· {uploadResolution.text} ({uploadResolution.label})</span>
                                        )}
                                    </p>
                                </div>
                            </div>
                            <div className="flex flex-col items-end gap-1">
                                <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
                                    <span className="h-2 w-2 rounded-full bg-[var(--accent)] animate-pulse" />
                                    {t('uploadReady')}
                                </div>
                                {videoInfo?.aspectWarning && (
                                    <div className="text-xs text-amber-400 flex items-center gap-1">
                                        ⚠️ Not 9:16 — subtitles may overflow
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="text-center py-12 relative">
                            <div className="text-6xl mb-3 opacity-80">📤</div>
                            <p className="text-2xl font-semibold mb-1">{t('uploadDropTitle')}</p>
                            <p className="text-[var(--muted)}">{t('uploadDropSubtitle')}</p>
                            <p className="text-xs text-[var(--muted)] mt-4">{t('uploadDropFootnote')}</p>
                        </div>
                    )}
                </div>

                {/* Controls Card - Only show when file is selected */}
                {selectedFile && !isProcessing && (
                    <div className="card space-y-4 animate-fade-in">
                        <div
                            className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] pb-3 cursor-pointer group"
                            onClick={() => setShowSettings(!showSettings)}
                        >
                            <div className="flex items-center gap-3">
                                <div>
                                    <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">{t('controlsLabel')}</p>
                                    <h3 className="text-xl font-semibold">{t('controlsTitle')}</h3>
                                </div>
                            </div>
                            <div className={`transition-transform duration-200 ${showSettings ? 'rotate-180' : ''}`}>
                                <svg className="w-5 h-5 text-[var(--muted)] group-hover:text-[var(--foreground)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                </svg>
                            </div>
                        </div>

                        {showSettings && (
                            <div className="space-y-5 pt-1 animate-fade-in">
                                <div>
                                    <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                        {t('engineLabel')}
                                    </label>
                                    <div className="grid grid-cols-2 gap-3">
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setTranscribeProvider('local');
                                                setTranscribeMode('turbo');
                                            }}
                                            className={`p-3 rounded-lg border text-left transition-all ${transcribeProvider === 'local'
                                                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                                                : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                }`}
                                        >
                                            <div className="font-semibold">{t('engineLocalTurbo')}</div>
                                            <div className="text-xs text-[var(--muted)]">{t('engineLocalDesc')}</div>
                                        </button>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setTranscribeProvider('openai');
                                                setTranscribeMode('balanced'); // Always use whisper-1 for ChatGPT API
                                            }}
                                            className={`p-3 rounded-lg border text-left transition-all ${transcribeProvider === 'openai'
                                                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                                                : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                }`}
                                        >
                                            <div className="font-semibold">ChatGPT API</div>
                                            <div className="text-xs text-[var(--muted)]">whisper-1 with karaoke</div>
                                        </button>
                                    </div>
                                </div>

                                {/* Removed OpenAI transcription quality controls - only whisper-1 available */}

                                {transcribeProvider === 'local' && (
                                    <div>
                                        <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                            Transcription Quality
                                        </label>
                                        <div className="grid grid-cols-2 gap-3">
                                            {([
                                                { mode: 'fast', label: 'Fast', desc: 'tiny model' },
                                                { mode: 'balanced', label: 'Balanced', desc: 'medium model' },
                                                { mode: 'turbo', label: 'Turbo', desc: 'large-v3-turbo' },
                                                { mode: 'best', label: 'Best', desc: 'large-v3' },
                                            ] as const).map(({ mode, label, desc }) => (
                                                <button
                                                    key={mode}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setTranscribeMode(mode as TranscribeMode);
                                                    }}
                                                    className={`p-2 rounded-lg border text-center text-sm transition-all ${transcribeMode === mode
                                                        ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)] font-medium'
                                                        : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                        }`}
                                                >
                                                    <div>{label}</div>
                                                    <div className="text-xs text-[var(--muted)]">{desc}</div>
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <div>
                                    <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                        {t('qualityLabel')}
                                    </label>
                                    <div className="grid grid-cols-3 gap-3">
                                        {(['low size', 'balanced', 'high quality'] as const).map((q) => (
                                            <button
                                                key={q}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setOutputQuality(q);
                                                }}
                                                className={`p-2 rounded-lg border text-center text-sm capitalize transition-all ${outputQuality === q
                                                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)] font-medium'
                                                    : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                    }`}
                                            >
                                                {q}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                        {t('resolutionLabel')}
                                    </label>
                                    <div className="grid grid-cols-2 gap-3">
                                        {([
                                            { value: '1080x1920', label: t('resolution1080') },
                                            { value: '2160x3840', label: t('resolution4k') },
                                        ] as const).map(({ value, label }) => (
                                            <button
                                                key={value}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setOutputResolutionChoice(value);
                                                }}
                                                className={`p-3 rounded-lg border text-left transition-all ${outputResolutionChoice === value
                                                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                                                    : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                    }`}
                                            >
                                                <div className="font-semibold">{label}</div>
                                                <div className="text-xs text-[var(--muted)]">{value.replace('x', '×')}</div>
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div className="pt-2">
                                    <label className="flex items-center gap-3 cursor-pointer group" onClick={(e) => e.stopPropagation()}>
                                        <div
                                            onClick={() => setUseAI(!useAI)}
                                            className={`w-12 h-6 rounded-full transition-colors relative ${useAI ? 'bg-[var(--accent)]' : 'bg-[var(--border)]'}`}
                                        >
                                            <div className={`absolute top-1 left-1 bg-white w-4 h-4 rounded-full transition-transform ${useAI ? 'translate-x-6' : ''}`} />
                                        </div>
                                        <span className="font-medium">{t('aiToggleLabel')}</span>
                                    </label>
                                    <p className="text-xs text-[var(--muted)] mt-1 ml-14">{t('aiToggleDescription')}</p>
                                </div>

                                {useAI && (
                                    <div className="animate-fade-in" onClick={(e) => e.stopPropagation()}>
                                        <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                                            {t('contextLabel')}
                                        </label>
                                        <textarea
                                            value={contextPrompt}
                                            onChange={(e) => setContextPrompt(e.target.value)}
                                            placeholder={t('contextPlaceholder')}
                                            className="input-field h-20 resize-none"
                                        />
                                    </div>
                                )}
                            </div>
                        )}

                        {showSettings && (
                            <div className="flex justify-end gap-3 pt-2">
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleResetSelection();
                                    }}
                                    className="btn-secondary"
                                >
                                    {t('processingReset')}
                                </button>
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setShowSettings(false);
                                        handleStart();
                                    }}
                                    disabled={isProcessing}
                                    className="btn-primary w-full sm:w-auto px-8"
                                >
                                    {t('controlsStart')}
                                </button>
                            </div>
                        )}
                    </div>
                )}

                {error && (
                    <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/30 text-[var(--danger)] px-6 py-4 rounded-xl animate-fade-in">
                        {error}
                    </div>
                )}


            </div>

            <div className="space-y-4">
                {(isProcessing || (selectedJob && selectedJob.status !== 'pending')) && (
                    <div className="card space-y-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                                <p className="text-xs uppercase tracking-[0.28em] text-[var(--muted)]">
                                    {selectedJob?.status === 'completed' ? t('liveOutputLabel') : t('statusProcessing')}
                                </p>
                                <h3 className="text-2xl font-semibold break-words [overflow-wrap:anywhere]">
                                    {selectedJob?.result_data?.original_filename || (isProcessing ? t('statusProcessingEllipsis') : t('liveOutputPlaceholderTitle'))}
                                </h3>
                                <p className="text-sm text-[var(--muted)]">{t('liveOutputSubtitle')}</p>
                            </div>
                            <span className={`px-3 py-1 rounded-full text-xs font-semibold border ${statusStyles[selectedJob?.status || (isProcessing ? 'processing' : 'pending')] || ''}`}>
                                {selectedJob?.status ? selectedJob.status.toUpperCase() : isProcessing ? t('liveOutputStatusProcessing') : t('liveOutputStatusIdle')}
                            </span>
                        </div>

                        {isProcessing && (
                            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 space-y-2 animate-fade-in">
                                <div className="flex items-center justify-between text-sm">
                                    <span className="font-medium">{statusMessage || t('progressLabel')}</span>
                                    <span className="text-[var(--accent)] font-semibold">{progress}%</span>
                                </div>
                                <div className="w-full bg-[var(--surface)] rounded-full h-2 overflow-hidden">
                                    <div
                                        className="bg-gradient-to-r from-[var(--accent)] to-[var(--accent-secondary)] h-2 rounded-full transition-all duration-300"
                                        style={{ width: `${progress}%` }}
                                    />
                                </div>
                            </div>
                        )}

                        {/* Strict check: Only show preview if NOT processing and job is completed */}
                        {!isProcessing && selectedJob && selectedJob.status === 'completed' ? (
                            <div className="animate-fade-in relative">
                                {/* Animated shimmer border */}
                                <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-r from-[var(--accent)] via-[var(--accent-secondary)] to-[var(--accent)] bg-[length:200%_100%] animate-shimmer opacity-80" />

                                {/* Inner glow */}
                                <div className="absolute inset-0 rounded-2xl" style={{ boxShadow: '0 0 60px -15px var(--accent), 0 0 30px -10px var(--accent-secondary)' }} />

                                <div className="relative rounded-2xl border border-white/10 bg-[var(--surface-elevated)] overflow-hidden">
                                    {/* Success badge */}
                                    <div className="absolute top-0 right-0 p-4 z-10">
                                        <div className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-gradient-to-r from-emerald-500/20 to-[var(--accent)]/20 backdrop-blur-md text-emerald-300 border border-emerald-500/30">
                                            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                                            Subtitles Ready
                                        </div>
                                    </div>

                                    <div className="flex flex-col sm:flex-row">
                                        {/* Preview Thumbnail Area */}
                                        <div
                                            onClick={() => videoUrl && setShowPreview(true)}
                                            className="relative group cursor-pointer w-full sm:w-1/3 aspect-video sm:aspect-auto sm:h-auto min-h-[180px] bg-black/40 flex items-center justify-center overflow-hidden"
                                        >
                                            {/* Real Video Preview as Thumbnail */}
                                            {videoUrl ? (
                                                <video
                                                    src={`${videoUrl}#t=0.5`}
                                                    className="absolute inset-0 w-full h-full object-cover opacity-70 group-hover:opacity-90 transition-opacity duration-300"
                                                    muted
                                                    playsInline
                                                    preload="metadata"
                                                />
                                            ) : (
                                                <div className="absolute inset-0 bg-gradient-to-br from-[var(--accent)]/20 to-[var(--accent-secondary)]/20 opacity-50" />
                                            )}

                                            {/* Play Button with glow */}
                                            <div className="relative z-10 w-16 h-16 rounded-full bg-white/15 backdrop-blur-sm border border-white/25 flex items-center justify-center group-hover:scale-110 group-hover:bg-white/25 transition-all duration-300" style={{ boxShadow: '0 0 25px rgba(255,255,255,0.2)' }}>
                                                <div className="w-0 h-0 border-t-[10px] border-t-transparent border-l-[18px] border-l-white border-b-[10px] border-b-transparent ml-1" />
                                            </div>

                                            <div className="absolute bottom-3 left-3 text-xs font-medium text-white/90 z-10 drop-shadow-lg">
                                                Click to Preview
                                            </div>
                                        </div>

                                        {/* Details Area */}
                                        <div className="p-6 flex-1 flex flex-col justify-center">
                                            <h4 className="text-xl font-semibold mb-2 line-clamp-2 bg-gradient-to-r from-white to-white/80 bg-clip-text">
                                                {selectedJob.result_data?.original_filename || "Processed Video.mp4"}
                                            </h4>
                                            <div className="flex flex-wrap gap-4 text-sm text-[var(--muted)] mb-6">
                                                <span className="flex items-center gap-1.5">
                                                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                                                    MP4
                                                </span>
                                                <span>•</span>
                                                <span>{((selectedJob.result_data?.output_size || selectedFile?.size || 0) / (1024 * 1024)).toFixed(1)} MB</span>
                                                {(displayResolution || selectedJob.result_data?.resolution) && (
                                                    <>
                                                        <span>•</span>
                                                        {displayResolution ? (
                                                            <>
                                                                <span className="text-[var(--accent)]">{displayResolution.text}</span>
                                                                <span className="text-[var(--muted)]">({displayResolution.label})</span>
                                                            </>
                                                        ) : (
                                                            <span className="text-[var(--accent)]">{selectedJob.result_data?.resolution}</span>
                                                        )}
                                                    </>
                                                )}
                                            </div>

                                            <div className="flex flex-wrap gap-3">
                                                {videoUrl && (
                                                    <button
                                                        className="btn-primary items-center gap-2 inline-flex disabled:opacity-50"
                                                        onClick={() => handleDownload(videoUrl, selectedJob.result_data?.original_filename || 'processed.mp4')}
                                                        disabled={isDownloading}
                                                    >
                                                        {isDownloading ? (
                                                            <><span className="animate-spin">⏳</span> Downloading...</>
                                                        ) : (
                                                            <>⬇️ Download MP4</>
                                                        )}
                                                    </button>
                                                )}
                                                <button
                                                    onClick={() => videoUrl && setShowPreview(true)}
                                                    className="btn-secondary"
                                                >
                                                    ▶️ Preview
                                                </button>
                                            </div>

                                            <ViralIntelligence jobId={selectedJob.id} />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ) : null}
                    </div>
                )}

                {/* Recent Jobs with Expiry */}
                <div className="card mt-6 border-none bg-transparent shadow-none p-0">
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                        <div>
                            <h3 className="text-lg font-semibold">History</h3>
                            <p className="text-xs text-[var(--muted)]">Items expire in 24 hours</p>
                        </div>
                        {jobsLoading && <span className="text-xs text-[var(--muted)]">{t('refreshingLabel')}</span>}
                    </div>
                    {recentJobs.length === 0 && (
                        <p className="text-[var(--muted)] text-sm">{t('noRunsYet')}</p>
                    )}
                    <div className="space-y-2">
                        {recentJobs.map((job) => {
                            const publicUrl = buildStaticUrl(job.result_data?.public_url || job.result_data?.video_path);
                            const timestamp = (job.updated_at || job.created_at) * 1000;
                            const isExpired = (Date.now() - timestamp) > 24 * 60 * 60 * 1000;

                            return (
                                <div
                                    key={job.id}
                                    className={`flex flex-wrap sm:flex-nowrap items-center justify-between gap-3 p-3 rounded-lg border ${isExpired ? 'border-[var(--border)]/30 bg-[var(--surface)] text-[var(--muted)]' : 'border-[var(--border)] bg-[var(--surface-elevated)]'} transition-colors`}
                                >
                                    <div className="min-w-0 flex-1">
                                        <div className="font-semibold text-sm truncate">
                                            {job.result_data?.original_filename || job.id}
                                        </div>
                                        <div className="text-xs text-[var(--muted)]">
                                            {formatDate(timestamp)}
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-2">
                                        {isExpired ? (
                                            <span className="text-xs bg-[var(--surface)] border border-[var(--border)] px-2 py-1 rounded text-[var(--muted)]">
                                                Expired
                                            </span>
                                        ) : (
                                            <>
                                                {job.status === 'completed' && publicUrl && (
                                                    <>
                                                        <a
                                                            className="text-xs btn-primary py-1.5 px-3 h-auto"
                                                            href={publicUrl}
                                                            download={job.result_data?.original_filename || 'processed.mp4'}
                                                        >
                                                            Download
                                                        </a>
                                                        <button
                                                            onClick={() => { onJobSelect(job); setShowPreview(true); }}
                                                            className="text-xs btn-secondary py-1.5 px-3 h-auto"
                                                        >
                                                            View
                                                        </button>
                                                    </>
                                                )}
                                                {/* Delete button */}
                                                {confirmDeleteId === job.id ? (
                                                    <div className="flex items-center gap-1">
                                                        <button
                                                            onClick={async () => {
                                                                setDeletingJobId(job.id);
                                                                try {
                                                                    await api.deleteJob(job.id);
                                                                    if (selectedJob?.id === job.id) {
                                                                        onJobSelect(null);
                                                                        setShowPreview(false);
                                                                    }
                                                                    setConfirmDeleteId(null);
                                                                    // Refresh jobs list without page reload
                                                                    await onRefreshJobs();
                                                                } catch (err) {
                                                                    console.error('Delete failed:', err);
                                                                } finally {
                                                                    setDeletingJobId(null);
                                                                }
                                                            }}
                                                            disabled={deletingJobId === job.id}
                                                            className="text-xs px-2 py-1 rounded bg-[var(--danger)] text-white hover:bg-[var(--danger)]/80 disabled:opacity-50"
                                                        >
                                                            {deletingJobId === job.id ? '...' : '✓'}
                                                        </button>
                                                        <button
                                                            onClick={() => setConfirmDeleteId(null)}
                                                            className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:bg-white/5"
                                                        >
                                                            ✕
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <button
                                                        onClick={() => setConfirmDeleteId(job.id)}
                                                        className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--danger)] hover:text-[var(--danger)] transition-colors"
                                                        title={t('deleteJob')}
                                                    >
                                                        🗑️
                                                    </button>
                                                )}
                                            </>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                <VideoModal
                    isOpen={showPreview}
                    onClose={() => setShowPreview(false)}
                    videoUrl={videoUrl || ''}
                />
            </div>
        </div >
    );
}
