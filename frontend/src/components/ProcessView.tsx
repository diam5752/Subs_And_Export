import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, JobResponse } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { VideoModal } from './VideoModal';
import { ViralIntelligence } from './ViralIntelligence';
import { SubtitlePositionSelector } from './SubtitlePositionSelector';
import { describeResolution, describeResolutionString, validateVideoAspectRatio } from '@/lib/video';

type TranscribeMode = 'balanced' | 'turbo';
type TranscribeProvider = 'local' | 'openai' | 'groq' | 'whispercpp';

interface ProcessViewProps {
    selectedFile: File | null;
    onFileSelect: (file: File | null) => void;
    isProcessing: boolean;
    progress: number;
    statusMessage: string;
    error: string;
    onStartProcessing: (options: ProcessingOptions) => Promise<void>;
    onReset: () => void;
    onCancelProcessing?: () => void;
    selectedJob: JobResponse | null;
    onJobSelect: (job: JobResponse | null) => void;
    recentJobs: JobResponse[];
    jobsLoading: boolean;
    statusStyles: Record<string, string>;
    formatDate: (ts: string | number) => string;
    buildStaticUrl: (path?: string | null) => string | null;
    onRefreshJobs: () => Promise<void>;
    // Pagination props
    currentPage: number;
    totalPages: number;
    onNextPage: () => void;
    onPrevPage: () => void;
    totalJobs: number;
    pageSize: number;
}


export interface ProcessingOptions {
    transcribeMode: TranscribeMode;
    transcribeProvider: TranscribeProvider;
    outputQuality: 'low size' | 'balanced' | 'high quality';
    outputResolution: '1080x1920' | '2160x3840';
    useAI: boolean;
    contextPrompt: string;
    subtitle_position: string;
    max_subtitle_lines: number;
    subtitle_color: string;
    shadow_strength: number;
    highlight_style: string;
    subtitle_size: string;
    karaoke_enabled: boolean;
}


export function ProcessView({
    selectedFile,
    onFileSelect,
    isProcessing,
    progress,
    statusMessage,
    error,
    onStartProcessing,
    onReset,
    onCancelProcessing,
    selectedJob,
    onJobSelect,
    recentJobs,
    jobsLoading,
    statusStyles,
    formatDate,
    buildStaticUrl,
    onRefreshJobs,
    currentPage,
    totalPages,
    totalJobs,
    pageSize,
    onNextPage,
    onPrevPage,
}: ProcessViewProps) {
    const { t } = useI18n();
    const fileInputRef = useRef<HTMLInputElement>(null);
    const resultsRef = useRef<HTMLDivElement>(null);
    const validationRequestId = useRef(0);
    const modelSectionRef = useRef<HTMLDivElement>(null);
    const customizeSectionRef = useRef<HTMLDivElement>(null);

    // Local state for options
    const [showPreview, setShowPreview] = useState(false);
    const [showSettings, setShowSettings] = useState(true);
    const [showExperiments, setShowExperiments] = useState(false);
    const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
    const [transcribeMode, setTranscribeMode] = useState<TranscribeMode>('turbo');
    const [transcribeProvider, setTranscribeProvider] = useState<TranscribeProvider>('local');
    // outputQuality state removed as it is now always high quality
    // const [outputQuality, setOutputQuality] = useState<'low size' | 'balanced' | 'high quality'>('balanced');
    const [subtitlePosition, setSubtitlePosition] = useState('default');
    const [maxSubtitleLines, setMaxSubtitleLines] = useState(0); // TikTok preset: 1 word at a time
    const [subtitleColor, setSubtitleColor] = useState<string>('#FFFF00'); // Default Yellow
    const [subtitleSize, setSubtitleSize] = useState('big'); // TikTok preset: big
    const [karaokeEnabled, setKaraokeEnabled] = useState(true);
    const [shadowStrength] = useState<number>(4); // Default Normal
    const [useAI, setUseAI] = useState(false);
    const [contextPrompt, setContextPrompt] = useState('');
    const [videoInfo, setVideoInfo] = useState<{ width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null } | null>(null);
    const [isDownloading, setIsDownloading] = useState(false);
    const [exportingResolutions, setExportingResolutions] = useState<Record<string, boolean>>({});
    const [outputResolutionInfo, setOutputResolutionInfo] = useState<{ text: string; label: string } | null>(null);
    const [expandedModelId, setExpandedModelId] = useState<string | null>(null);

    // Color Palette
    const SUBTITLE_COLORS = [
        { label: t('colorYellow'), value: '#FFFF00', ass: '&H0000FFFF' },
        { label: t('colorWhite'), value: '#FFFFFF', ass: '&H00FFFFFF' },
        { label: t('colorCyan'), value: '#00FFFF', ass: '&H00FFFF00' },
        { label: t('colorGreen'), value: '#00FF00', ass: '&H0000FF00' },
        { label: t('colorMagenta'), value: '#FF00FF', ass: '&H00FF00FF' },
    ];

    // Style Presets
    const STYLE_PRESETS = [
        {
            id: 'tiktok',
            name: t('styleTiktokName'),
            description: t('styleTiktokDesc'),
            emoji: '🔥',
            settings: {
                position: 'default',
                size: 'big',
                lines: 0, // 1 word at a time
                color: '#FFFF00',
                karaoke: true,
            },
            colorClass: 'from-pink-500 to-orange-500',
        },
        {
            id: 'cinematic',
            name: t('styleCinematicName'),
            description: t('styleCinematicDesc'),
            emoji: '🎬',
            settings: {
                position: 'bottom',
                size: 'medium',
                lines: 2,
                color: '#FFFFFF',
                karaoke: false,
            },
            colorClass: 'from-slate-500 to-zinc-600',
        },
        {
            id: 'minimal',
            name: t('styleMinimalName'),
            description: t('styleMinimalDesc'),
            emoji: '✨',
            settings: {
                position: 'bottom',
                size: 'small',
                lines: 3,
                color: '#00FFFF',
                karaoke: false,
            },
            colorClass: 'from-cyan-500 to-teal-500',
        },
    ];

    const [activePreset, setActivePreset] = useState<string | null>('tiktok');
    const [showCustomize, setShowCustomize] = useState(false);

    const AVAILABLE_MODELS = [
        {
            id: 'standard',
            name: t('modelStandardName'),
            description: t('modelStandardDesc'),
            badge: t('modelStandardBadge'),
            badgeColor: 'text-[var(--muted)] bg-[var(--surface)]',
            provider: 'whispercpp',
            mode: 'turbo',
            stats: { speed: 4, accuracy: 3, karaoke: false, linesControl: false },
            icon: (selected: boolean) => (
                <div className={`p-2 rounded-lg ${selected ? 'bg-cyan-500/20 text-cyan-300' : 'bg-cyan-500/10 text-cyan-500'}`}>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
                    </svg>
                </div>
            ),
            colorClass: (selected: boolean) => selected
                ? 'border-cyan-500 bg-cyan-500/10 ring-1 ring-cyan-500'
                : 'border-[var(--border)] hover:border-cyan-500/50 hover:bg-cyan-500/5'
        },
        {
            id: 'enhanced',
            name: t('modelEnhancedName'),
            description: t('modelEnhancedDesc'),
            badge: t('modelEnhancedBadge'),
            badgeColor: 'text-amber-400 bg-amber-400/10',
            provider: 'local',
            mode: 'turbo',
            stats: { speed: 2, accuracy: 5, karaoke: true, linesControl: true },
            icon: (selected: boolean) => (
                <div className={`p-2 rounded-lg ${selected ? 'bg-violet-500/20 text-violet-300' : 'bg-violet-500/10 text-violet-500'}`}>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                    </svg>
                </div>
            ),
            colorClass: (selected: boolean) => selected
                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                : 'border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--accent)]/5'
        },
        {
            id: 'ultimate',
            name: t('modelUltimateName'),
            description: t('modelUltimateDesc'),
            badge: t('modelUltimateBadge'),
            badgeColor: 'text-purple-400 bg-purple-500/10',
            provider: 'groq',
            mode: 'turbo',
            stats: { speed: 5, accuracy: 5, karaoke: true, linesControl: true },
            icon: (selected: boolean) => (
                <div className={`p-2 rounded-lg ${selected ? 'bg-purple-500/20 text-purple-300' : 'bg-purple-500/10 text-purple-400'}`}>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                </div>
            ),
            colorClass: (selected: boolean) => selected
                ? 'border-purple-500 bg-purple-500/10 ring-1 ring-purple-500'
                : 'border-[var(--border)] hover:border-purple-500/50 hover:bg-purple-500/5'
        }
    ];

    // Selection mode state for batch delete
    const [selectionMode, setSelectionMode] = useState(false);
    const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set());
    const [isBatchDeleting, setIsBatchDeleting] = useState(false);
    const [confirmBatchDelete, setConfirmBatchDelete] = useState(false);

    // Drag and drop state
    const [isDragOver, setIsDragOver] = useState(false);

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0] || null;
        onFileSelect(file);
    };

    // Drag and drop handlers
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
        // Only set to false if we're leaving the drop zone (not a child element)
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
            // Check if it's a video file
            if (file.type.startsWith('video/') || /\.(mp4|mov|mkv|webm|avi)$/i.test(file.name)) {
                onFileSelect(file);
            }
        }
    }, [isProcessing, onFileSelect]);

    useEffect(() => {
        if (!selectedFile) {
            validationRequestId.current += 1;
            setVideoInfo(null);
            return;
        }

        const requestId = ++validationRequestId.current;
        validateVideoAspectRatio(selectedFile).then(info => {
            if (requestId === validationRequestId.current) {
                setVideoInfo(info);
            }
        });
    }, [selectedFile]);

    const handleResetSelection = () => {
        validationRequestId.current += 1;
        setVideoInfo(null);
        setSubtitlePosition('default');
        setMaxSubtitleLines(2);
        setSubtitleSize('medium');
        setKaraokeEnabled(true);
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

    const handleExport = async (resolution: string) => {
        if (!selectedJob) return;

        // If we already have this variant, just download it
        if (selectedJob.result_data?.variants?.[resolution]) {
            const url = buildStaticUrl(selectedJob.result_data.variants[resolution]);
            if (url) {
                handleDownload(url, `processed_${resolution}.mp4`);
                return;
            }
        }

        // Otherwise, trigger export
        setExportingResolutions(prev => ({ ...prev, [resolution]: true }));
        try {
            const updatedJob = await api.exportVideo(selectedJob.id, resolution);
            onJobSelect(updatedJob);
        } catch (err) {
            console.error('Export failed:', err);
        } finally {
            setExportingResolutions(prev => ({ ...prev, [resolution]: false }));
        }
    };

    const handleStart = () => {
        setShowPreview(false); // Hide any previous preview

        // Force scroll immediately for better UX
        resultsRef.current?.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
        });

        const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];

        onStartProcessing({
            transcribeMode,
            transcribeProvider,
            outputQuality: 'high quality',
            outputResolution: '1080x1920', // Always preview in 1080p
            useAI,
            contextPrompt,
            subtitle_position: subtitlePosition,
            max_subtitle_lines: maxSubtitleLines,
            subtitle_color: colorObj.ass,
            shadow_strength: shadowStrength,
            highlight_style: 'active-graphics',
            subtitle_size: subtitleSize,
            karaoke_enabled: karaokeEnabled,
        });
    };

    const videoUrl = buildStaticUrl(selectedJob?.result_data?.public_url || selectedJob?.result_data?.video_path);
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
            /* istanbul ignore next -- video events not testable in JSDOM */
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
            /* istanbul ignore next -- video events not testable in JSDOM */
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

    // Auto-scroll to results when processing starts
    useEffect(() => {
        if (isProcessing && resultsRef.current) {
            // Small delay to ensure render cycle is complete and UI is ready
            setTimeout(() => {
                resultsRef.current?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start',
                });
            }, 100);
        }
    }, [isProcessing]);

    const describeModel = (provider?: string, model?: string): { text: string; label: string } | null => {
        if (provider === 'groq') {
            return { text: 'Groq Turbo', label: 'Cloud' };
        }
        if (provider === 'openai') {
            return { text: 'ChatGPT API', label: 'Cloud' };
        }
        if (provider === 'whispercpp') {
            return { text: 'whisper.cpp', label: 'Metal' };
        }
        if (model?.includes('large-v3-turbo')) {
            return { text: 'Turbo', label: 'Local' };
        }
        return model ? { text: model, label: 'Custom' } : null;
    };

    const modelInfo = describeModel(selectedJob?.result_data?.transcribe_provider, selectedJob?.result_data?.model_size);

    // Handler functions (extracted for testability)
    const handleUploadCardClick = useCallback(() => {
        if (!isProcessing) {
            fileInputRef.current?.click();
        }
    }, [isProcessing]);

    /* istanbul ignore next -- modal handlers tested in E2E */
    const handleOpenPreview = useCallback(() => {
        if (videoUrl) {
            setShowPreview(true);
        }
    }, [videoUrl]);

    /* istanbul ignore next -- modal handlers tested in E2E */
    const handleClosePreview = useCallback(() => {
        setShowPreview(false);
    }, []);



    return (
        <div className="grid xl:grid-cols-[1.05fr,0.95fr] gap-6">
            <div className="space-y-4">
                {/* Upload Card */}
                <div
                    className={`card relative overflow-hidden cursor-pointer group transition-all ${isDragOver
                        ? 'border-[var(--accent)] border-2 border-dashed bg-[var(--accent)]/10 scale-[1.02]'
                        : 'hover:border-[var(--accent)]/60'
                        }`}
                    data-clickable="true"
                    onClick={handleUploadCardClick}
                    onDragEnter={handleDragEnter}
                    onDragLeave={handleDragLeave}
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                >
                    <div className={`absolute inset-0 transition-opacity pointer-events-none ${isDragOver
                        ? 'opacity-100 bg-gradient-to-br from-[var(--accent)]/20 via-transparent to-[var(--accent-secondary)]/25'
                        : 'opacity-0 group-hover:opacity-100 bg-gradient-to-br from-[var(--accent)]/5 via-transparent to-[var(--accent-secondary)]/10'
                        }`} />
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/mp4,video/quicktime,video/x-matroska"
                        onChange={handleFileChange}
                        className="hidden"
                        disabled={isProcessing}
                    />
                    {isDragOver ? (
                        <div className="text-center py-12 relative">
                            <div className="text-6xl mb-3 animate-bounce">📥</div>
                            <p className="text-2xl font-semibold mb-1 text-[var(--accent)]">{t('dropFileHere')}</p>
                            <p className="text-[var(--muted)]">{t('releaseToUpload')}</p>
                        </div>
                    ) : selectedFile ? (

                        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between relative">
                            <div className="flex items-start gap-3">
                                {/* Video Thumbnail */}
                                {videoInfo?.thumbnailUrl ? (
                                    <div className="w-16 h-16 rounded-lg overflow-hidden bg-black/40 flex-shrink-0">
                                        {/* eslint-disable-next-line @next/next/no-img-element */}
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
                                        <span aria-hidden="true">⚠️</span>
                                        {t('aspectRatioWarning')}
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="text-center py-12 relative">
                            <div className="text-6xl mb-3 opacity-80">📤</div>
                            <p className="text-2xl font-semibold mb-1">{t('uploadDropTitle')}</p>
                            <p className="text-[var(--muted)]">{t('uploadDropSubtitle')}</p>
                            <p className="text-xs text-[var(--muted)] mt-4">{t('uploadDropFootnote')}</p>
                        </div>
                    )}
                </div>
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
                                <div ref={modelSectionRef}>
                                    <label className="block text-sm font-medium text-[var(--muted)] mb-3">
                                        {t('transcriptionModelLabel')}
                                    </label>

                                    {/* Check if we have a selected model and are in collapsed state */}
                                    {(() => {
                                        const selectedModel = AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode);
                                        const isExpanded = expandedModelId === 'all';

                                        if (selectedModel && !isExpanded) {
                                            // Collapsed view - show only selected model
                                            return (
                                                <button
                                                    data-testid="model-selector-collapsed"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setExpandedModelId('all');
                                                        setTimeout(() => {
                                                            modelSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                                                        }, 50);
                                                    }}
                                                    className={`w-full p-3 rounded-xl border text-left transition-all flex items-center gap-3 ${selectedModel.colorClass(true)}`}
                                                >
                                                    {selectedModel.icon(true)}
                                                    <div className="flex-1 min-w-0">
                                                        <div className="flex items-center gap-2">
                                                            <span className="font-semibold text-base">{selectedModel.name}</span>
                                                            <div className={`w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0 ${selectedModel.provider === 'groq' ? 'bg-purple-500' :
                                                                selectedModel.provider === 'whispercpp' ? 'bg-cyan-500' :
                                                                    'bg-[var(--accent)]'
                                                                }`}>
                                                                <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                                                </svg>
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-2 mt-0.5">
                                                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${selectedModel.badgeColor}`}>
                                                                {selectedModel.badge}
                                                            </span>
                                                            <span className="text-xs text-[var(--muted)]">
                                                                {selectedModel.description}
                                                            </span>
                                                        </div>
                                                    </div>
                                                    <div className="flex items-center gap-1 text-xs text-[var(--muted)]">
                                                        <span>{t('changeModel')}</span>
                                                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                                        </svg>
                                                    </div>
                                                </button>
                                            );
                                        }

                                        // Expanded view - show all models
                                        return (
                                            <>
                                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 animate-slide-down">
                                                    {AVAILABLE_MODELS.map((model) => {
                                                        const isSelected = transcribeProvider === model.provider && transcribeMode === model.mode;

                                                        // Helper for stat bars (5 dots)
                                                        const renderStat = (value: number, max: number = 5) => (
                                                            <div className="flex gap-0.5">
                                                                {Array.from({ length: max }).map((_, i) => (
                                                                    <div
                                                                        key={i}
                                                                        className={`h-1.5 w-full rounded-full transition-colors ${i < value
                                                                            ? (isSelected ? 'bg-current opacity-80' : 'bg-[var(--foreground)] opacity-60')
                                                                            : 'bg-[var(--foreground)] opacity-20'
                                                                            }`}
                                                                    />
                                                                ))}
                                                            </div>
                                                        );

                                                        return (
                                                            <button
                                                                key={model.id}
                                                                data-testid={`model-${model.provider === 'local' ? 'turbo' : model.provider}`}
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    setTranscribeProvider(model.provider as TranscribeProvider);
                                                                    setTranscribeMode(model.mode as TranscribeMode);
                                                                    setExpandedModelId(null); // Collapse after selection
                                                                }}
                                                                className={`p-4 rounded-xl border text-left transition-all relative overflow-hidden group flex flex-col h-full ${model.colorClass(isSelected)}`}
                                                            >
                                                                <div className="flex items-start justify-between mb-2 w-full">
                                                                    {model.icon(isSelected)}
                                                                    {isSelected && (
                                                                        <div className={`w-5 h-5 rounded-full flex items-center justify-center ${model.provider === 'groq' ? 'bg-purple-500' :
                                                                            model.provider === 'whispercpp' ? 'bg-cyan-500' :
                                                                                'bg-[var(--accent)]'
                                                                            }`}>
                                                                            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                                                            </svg>
                                                                        </div>
                                                                    )}
                                                                </div>
                                                                <div className="font-semibold text-base mb-1">{model.name}</div>
                                                                <div className="text-sm text-[var(--muted)] mb-4">{model.description}</div>

                                                                {/* Game-like Stats */}
                                                                <div className="mt-auto space-y-2 mb-3">
                                                                    <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                                                        <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statSpeed')}</span>
                                                                        {renderStat(model.stats.speed)}
                                                                    </div>
                                                                    <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                                                        <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statAccuracy')}</span>
                                                                        {renderStat(model.stats.accuracy)}
                                                                    </div>
                                                                    <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                                                        <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statKaraoke')}</span>
                                                                        <div className={`text-[10px] font-bold ${model.stats.karaoke ? 'text-emerald-500' : 'text-[var(--muted)]'}`}>
                                                                            {model.stats.karaoke ? t('statKaraokeSupported') : t('statKaraokeNo')}
                                                                        </div>
                                                                    </div>
                                                                    <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                                                        <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statLines')}</span>
                                                                        <div className={`text-[10px] font-bold ${model.stats.linesControl ? 'text-emerald-500' : 'text-cyan-400'}`}>
                                                                            {model.stats.linesControl ? t('statLinesCustom') : t('statLinesAuto')}
                                                                        </div>
                                                                    </div>
                                                                </div>

                                                                <div className="flex items-center gap-2 text-xs pt-3 border-t border-[var(--border)]/50">
                                                                    <span className={`px-2 py-0.5 rounded-full font-medium ${model.badgeColor}`}>
                                                                        {model.badge}
                                                                    </span>
                                                                </div>
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                                {/* Collapse button after selection */}
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setExpandedModelId(null);
                                                    }}
                                                    className="mt-2 text-xs text-[var(--muted)] hover:text-[var(--foreground)] flex items-center gap-1 transition-colors"
                                                >
                                                    <svg className="w-3 h-3 rotate-180" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                                    </svg>
                                                    {t('collapseModel')}
                                                </button>
                                            </>
                                        );
                                    })()}
                                </div>

                                {/* Style Presets */}
                                <div ref={customizeSectionRef}>
                                    <label className="block text-sm font-medium text-[var(--muted)] mb-3">
                                        {t('subtitleStyleLabel')}
                                    </label>
                                    <div className="grid grid-cols-3 gap-3 mb-3">
                                        {STYLE_PRESETS.map((preset) => {
                                            // Helper to get preview position
                                            const getPreviewBottom = (pos: string) => {
                                                switch (pos) {
                                                    case 'top': return '28%';
                                                    case 'bottom': return '8%';
                                                    default: return '18%';
                                                }
                                            };
                                            // Helper to get size scale - more dramatic differences
                                            const getSizeScale = (size: string) => {
                                                switch (size) {
                                                    case 'small': return 0.6;
                                                    case 'big': return 1.4;
                                                    default: return 1.0;
                                                }
                                            };
                                            // Bar height based on size
                                            const getBarHeight = (size: string) => {
                                                switch (size) {
                                                    case 'small': return 'h-1.5';
                                                    case 'big': return 'h-4';
                                                    default: return 'h-2.5';
                                                }
                                            };

                                            return (
                                                <button
                                                    key={preset.id}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setActivePreset(preset.id);
                                                        setSubtitlePosition(preset.settings.position);
                                                        setSubtitleSize(preset.settings.size);
                                                        setMaxSubtitleLines(preset.settings.lines);
                                                        setSubtitleColor(preset.settings.color);
                                                        setKaraokeEnabled(preset.settings.karaoke);
                                                        // Keep settings open if already open, so user sees the changes
                                                    }}
                                                    className={`p-3 rounded-xl border text-left transition-all relative overflow-hidden ${activePreset === preset.id
                                                        ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]'
                                                        : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                        }`}
                                                >
                                                    {/* Gradient background */}
                                                    <div className={`absolute inset-0 bg-gradient-to-br ${preset.colorClass} opacity-10`} />

                                                    <div className="relative flex gap-3">
                                                        {/* Mini Phone Preview */}
                                                        <div className="flex-shrink-0 w-[70px] h-[120px] bg-slate-800 rounded-[12px] border-2 border-slate-700 overflow-hidden relative shadow-lg">
                                                            {/* Video Thumbnail or Gradient background */}
                                                            {videoInfo?.thumbnailUrl ? (
                                                                <>
                                                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                                                    <img
                                                                        src={videoInfo.thumbnailUrl}
                                                                        alt=""
                                                                        className="absolute inset-0 w-full h-full object-cover"
                                                                    />
                                                                    {/* Dark overlay for better subtitle visibility */}
                                                                    <div className="absolute inset-0 bg-black/40" />
                                                                </>
                                                            ) : (
                                                                <div className="absolute inset-0 bg-gradient-to-br from-slate-700 via-slate-800 to-slate-900" />
                                                            )}
                                                            {/* Mini notch */}
                                                            <div className="absolute top-1.5 left-1/2 -translate-x-1/2 w-5 h-1.5 bg-black/50 rounded-full" />
                                                            {/* Mini UI elements - social icons */}
                                                            <div className="absolute bottom-5 right-1 flex flex-col gap-1.5">
                                                                <div className="w-2 h-2 bg-white/30 rounded-full" />
                                                                <div className="w-2 h-2 bg-white/30 rounded-full" />
                                                                <div className="w-2 h-2 bg-white/30 rounded-full" />
                                                            </div>
                                                            {/* Subtitle bars - clear size differences */}
                                                            <div
                                                                className="absolute left-2 right-2 flex flex-col gap-0.5 items-center"
                                                                style={{ bottom: getPreviewBottom(preset.settings.position) }}
                                                            >
                                                                {Array.from({ length: preset.settings.lines === 0 ? 1 : Math.min(preset.settings.lines, 3) }).map((_, i) => {
                                                                    // Font size mapping: Increased line-heights to prevent overlap
                                                                    const fontSize = preset.settings.size === 'big' ? '11px' : preset.settings.size === 'small' ? '7px' : '8px';
                                                                    const lineHeight = preset.settings.size === 'big' ? '14px' : preset.settings.size === 'small' ? '9px' : '10px';

                                                                    // Sample text with more "viral" feel
                                                                    const text = preset.settings.lines === 0
                                                                        ? (preset.settings.karaoke ? (i % 2 === 0 ? t('previewWatch') : t('previewThis')) : t('previewWord'))
                                                                        : preset.id === 'cinematic'
                                                                            ? (i === 0 ? t('previewTheJourney') : t('previewBeginsHere'))
                                                                            : (i === 0 ? t('previewCleanDesign') : i === 1 ? t('previewForEveryone') : t('previewToRead'));

                                                                    return (
                                                                        <div
                                                                            key={i}
                                                                            className="flex items-center justify-center w-full"
                                                                            style={{ height: lineHeight }}
                                                                        >
                                                                            <span
                                                                                style={{
                                                                                    fontSize: fontSize,
                                                                                    fontWeight: 800,
                                                                                    color: preset.settings.color,
                                                                                    // Stronger shadow for better visibility/pop
                                                                                    textShadow: `0 2px 4px rgba(0,0,0,0.9), 0 0 8px ${preset.settings.color}60`,
                                                                                    lineHeight: 1,
                                                                                    fontFamily: 'Inter, sans-serif',
                                                                                    textTransform: 'uppercase',
                                                                                    whiteSpace: 'nowrap', // Prevent wrapping overlap
                                                                                }}
                                                                            >
                                                                                {text}
                                                                            </span>
                                                                        </div>
                                                                    );
                                                                })}
                                                            </div>
                                                            {/* Karaoke indicator */}
                                                            {preset.settings.karaoke && (
                                                                <div className="absolute top-1.5 right-1.5 w-2 h-2 bg-emerald-400 rounded-full animate-pulse shadow-sm" title="Karaoke" />
                                                            )}
                                                        </div>

                                                        {/* Text content */}
                                                        <div className="flex-1 min-w-0">
                                                            <div className="flex items-center gap-1.5 mb-1">
                                                                <span className="text-base">{preset.emoji}</span>
                                                                <span className="font-semibold text-sm truncate">{preset.name}</span>
                                                            </div>
                                                            <p className="text-[11px] text-[var(--muted)] leading-tight mb-1">{preset.description}</p>
                                                            {/* Detailed Specs - Split into 2 lines */}
                                                            <div className="flex flex-col gap-1 mt-1.5 opacity-80">
                                                                <div className="flex gap-1">
                                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--surface-elevated)] border border-[var(--border)] text-[var(--muted)] whitespace-nowrap">
                                                                        {preset.settings.size === 'big' ? t('sizeBig') : preset.settings.size === 'medium' ? t('sizeMedium') : t('sizeSmall')}
                                                                    </span>
                                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--surface-elevated)] border border-[var(--border)] text-[var(--muted)] whitespace-nowrap">
                                                                        {preset.settings.color === '#FFFF00' ? t('colorYellow') : preset.settings.color === '#FFFFFF' ? t('colorWhite') : t('colorCyan')}
                                                                    </span>
                                                                </div>
                                                                <div className="flex gap-1">
                                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--surface-elevated)] border border-[var(--border)] text-[var(--muted)] whitespace-nowrap">
                                                                        {preset.settings.position === 'default' ? t('positionMiddle') : preset.settings.position === 'bottom' ? t('positionLow') : t('positionHigh')}
                                                                    </span>
                                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--surface-elevated)] border border-[var(--border)] text-[var(--muted)] whitespace-nowrap">
                                                                        {preset.settings.lines === 0 ? t('lines1WordBadge') : `${preset.settings.lines} ${t('statLines')}`}
                                                                    </span>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </div>

                                                    {activePreset === preset.id && (
                                                        <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-[var(--accent)] flex items-center justify-center">
                                                            <svg className="w-2.5 h-2.5 text-[#031018]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                                            </svg>
                                                        </div>
                                                    )}
                                                </button>
                                            );
                                        })}
                                    </div>

                                    {/* Customize Toggle */}
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            const wasHidden = !showCustomize;
                                            setShowCustomize(!showCustomize);
                                            if (wasHidden) {
                                                setTimeout(() => {
                                                    customizeSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                                                }, 200);
                                            }
                                        }}
                                        className="w-full mt-4 p-3 rounded-lg bg-[var(--surface-elevated)] border border-[var(--border)] hover:border-[var(--accent)] hover:bg-[var(--surface-elevated)]/80 flex items-center justify-center gap-2 text-sm font-medium text-[var(--foreground)] transition-all shadow-sm"
                                    >
                                        <svg className={`w-4 h-4 transition-transform ${showCustomize ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                                        </svg>
                                        {showCustomize ? t('customizeHide') : t('customizeShow')}
                                    </button>
                                </div>

                                {/* Subtitle Position & Max Lines (only if customizing) */}
                                {showCustomize && (
                                    <div onClick={(e) => e.stopPropagation()} className="animate-slide-down">
                                        <SubtitlePositionSelector
                                            value={subtitlePosition}
                                            onChange={(v) => { setSubtitlePosition(v); setActivePreset(null); }}
                                            lines={maxSubtitleLines}
                                            onChangeLines={(v) => { setMaxSubtitleLines(v); setActivePreset(null); }}
                                            previewColor={subtitleColor}
                                            thumbnailUrl={videoInfo?.thumbnailUrl}
                                            subtitleColor={subtitleColor}
                                            onChangeColor={(v) => { setSubtitleColor(v); setActivePreset(null); }}
                                            colors={SUBTITLE_COLORS}
                                            disableMaxLines={transcribeProvider === 'whispercpp'}
                                            subtitleSize={subtitleSize}
                                            onChangeSize={(v) => { setSubtitleSize(v); setActivePreset(null); }}
                                            karaokeEnabled={karaokeEnabled}
                                            onChangeKaraoke={(v) => { setKaraokeEnabled(v); setActivePreset(null); }}
                                            karaokeSupported={AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode)?.stats.karaoke || false}
                                        />
                                    </div>
                                )}




                                {/* 🧪 Experimenting Section Toggle */}
                                {/* 🧪 Experimenting Section Toggle */}
                                <div className="border-t border-dashed border-[var(--border)] pt-4 mt-2">
                                    <button
                                        data-testid="experimenting-toggle"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            setShowExperiments(!showExperiments);
                                        }}
                                        className="flex items-center gap-2 mb-3 w-full hover:opacity-80 transition-opacity"
                                    >
                                        <span className="text-lg">🧪</span>
                                        <label className="text-sm font-medium text-[var(--muted)] cursor-pointer">
                                            {t('experimentingLabel')}
                                        </label>
                                        <span className="bg-purple-500/10 text-purple-400 text-[10px] px-1.5 py-0.5 rounded-full font-medium">
                                            {t('betaBadge')}
                                        </span>
                                        <svg
                                            className={`w-4 h-4 ml-auto text-[var(--muted)] transition-transform duration-200 ${showExperiments ? 'rotate-180' : ''}`}
                                            fill="none"
                                            viewBox="0 0 24 24"
                                            stroke="currentColor"
                                        >
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                        </svg>
                                    </button>

                                    {showExperiments && (
                                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 animate-in fade-in slide-in-from-top-2 duration-200">
                                            {/* ChatGPT API */}
                                            <button
                                                data-testid="model-chatgpt"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setTranscribeProvider('openai');
                                                    setTranscribeMode('balanced');
                                                }}
                                                className={`p-4 rounded-xl border border-dashed text-left transition-all relative overflow-hidden group ${transcribeProvider === 'openai'
                                                    ? 'border-emerald-500 bg-emerald-500/10 ring-1 ring-emerald-500'
                                                    : 'border-[var(--border)] hover:border-emerald-500/50 hover:bg-emerald-500/5'
                                                    }`}
                                            >
                                                <div className="flex items-start justify-between mb-2">
                                                    <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-500">
                                                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                                                        </svg>
                                                    </div>
                                                    {transcribeProvider === 'openai' && (
                                                        <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center">
                                                            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                                            </svg>
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="font-semibold text-base mb-1">{t('modelChatgptName')}</div>
                                                <div className="text-sm text-[var(--muted)] mb-2">{t('modelChatgptDesc')}</div>
                                                <div className="flex items-center gap-2 text-xs text-[var(--muted)]/80">
                                                    <span className="bg-emerald-500/10 text-emerald-500 px-1.5 py-0.5 rounded">whisper-1</span>
                                                </div>
                                            </button>
                                        </div>
                                    )}
                                </div>




                                {/* AI & Context */}
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
                                        {t('controlsStart') || 'Generate Preview'}
                                    </button>
                                </div>
                            </div>
                        )}

                        {error && (
                            <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/30 text-[var(--danger)] px-6 py-4 rounded-xl animate-fade-in">
                                {error}
                            </div>
                        )}
                    </div>
                )}

                <div className="space-y-4" ref={resultsRef} style={{ scrollMarginTop: '100px' }}>
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
                                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 space-y-3 animate-fade-in">
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
                                                onClick={onCancelProcessing}
                                                className="px-4 py-1.5 rounded-lg text-sm font-medium bg-[var(--danger)]/10 text-[var(--danger)] hover:bg-[var(--danger)]/20 border border-[var(--danger)]/30 transition-colors"
                                            >
                                                {t('cancelProcessing')}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* Strict check: Only show preview if NOT processing and job is completed */}
                            {!isProcessing && selectedJob && selectedJob.status === 'completed' ? (
                                <div className="animate-fade-in relative">
                                    {/* Animated shimmer border */}
                                    <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-r from-[var(--accent)] via-[var(--accent-secondary)] to-[var(--accent)] bg-[length:200%_100%] animate-shimmer opacity-80" />

                                    {/* Inner glow */}
                                    <div className="preview-card-glow absolute inset-0 rounded-2xl" />

                                    <div className="relative rounded-2xl border border-white/10 bg-[var(--surface-elevated)] overflow-hidden">
                                        {/* Success badge */}
                                        <div className="absolute top-0 right-0 p-4 z-10">
                                            <div className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-gradient-to-r from-emerald-500/20 to-[var(--accent)]/20 backdrop-blur-md text-emerald-300 border border-emerald-500/30">
                                                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                                                {t('subtitlesReady')}
                                            </div>
                                        </div>

                                        <div className="flex flex-col sm:flex-row">
                                            {/* Preview Thumbnail Area */}
                                            <div
                                                onClick={handleOpenPreview}
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
                                                <div className="play-button-glow relative z-10 w-16 h-16 rounded-full bg-white/15 backdrop-blur-sm border border-white/25 flex items-center justify-center group-hover:scale-110 group-hover:bg-white/25 transition-all duration-300">
                                                    <div className="w-0 h-0 border-t-[10px] border-t-transparent border-l-[18px] border-l-white border-b-[10px] border-b-transparent ml-1" />
                                                </div>

                                                <div className="absolute bottom-3 left-3 text-xs font-medium text-white/90 z-10 drop-shadow-lg">
                                                    {t('clickToPreview')}
                                                </div>
                                            </div>

                                            {/* Details Area */}
                                            <div className="p-6 flex-1 flex flex-col justify-center">
                                                <h4 className="text-xl font-semibold mb-2 line-clamp-2 bg-gradient-to-r from-white to-white/80 bg-clip-text">
                                                    {selectedJob.result_data?.original_filename || t('processedVideoFallback')}
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
                                                    {modelInfo && (
                                                        <>
                                                            <span>•</span>
                                                            <span className="flex items-center gap-1.5">
                                                                <svg className="w-4 h-4 text-[var(--accent)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                                                                </svg>
                                                                <span className="text-[var(--accent)]">{modelInfo.text}</span>
                                                                <span className="text-[var(--muted)]">({modelInfo.label})</span>
                                                            </span>
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
                                                            ⬇️ {t('downloadHd')}
                                                        </button>
                                                    )}

                                                    {videoUrl && (
                                                        <button
                                                            className={`items-center gap-2 inline-flex disabled:opacity-50 px-4 py-2 rounded-lg font-medium transition-colors ${selectedJob.result_data?.variants?.['2160x3840']
                                                                ? 'bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 border border-purple-500/30'
                                                                : 'bg-transparent border border-[var(--border)] hover:bg-white/5 text-[var(--muted)]'
                                                                }`}
                                                            onClick={() => handleExport('2160x3840')}
                                                            disabled={exportingResolutions['2160x3840']}
                                                        >
                                                            {exportingResolutions['2160x3840'] ? (
                                                                <><span className="animate-spin">⏳</span> {t('generating4k')}</>
                                                            ) : selectedJob.result_data?.variants?.['2160x3840'] ? (
                                                                <>⬇️ {t('download4k')}</>
                                                            ) : (
                                                                <>✨ {t('export4k')}</>
                                                            )}
                                                        </button>
                                                    )}

                                                    <button
                                                        onClick={handleOpenPreview}
                                                        className="btn-secondary"
                                                    >
                                                        ▶️ {t('previewButton')}
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
                                <h3 className="text-lg font-semibold">{t('historyTitle') || 'History'}</h3>
                                <p className="text-xs text-[var(--muted)]">{t('historyExpiry') || 'Items expire in 24 hours'}</p>
                            </div>
                            <div className="flex items-center gap-2">
                                {jobsLoading && <span data-testid="jobs-loading" className="text-xs text-[var(--muted)]">{t('refreshingLabel')}</span>}
                                {recentJobs.length > 0 && (
                                    <button
                                        onClick={() => {
                                            setSelectionMode(!selectionMode);
                                            if (selectionMode) {
                                                setSelectedJobIds(new Set());
                                                setConfirmBatchDelete(false);
                                            }
                                        }}
                                        className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${selectionMode
                                            ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                                            : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                            }`}
                                    >
                                        {selectionMode ? (t('cancelSelect') || 'Cancel') : (t('selectMode') || 'Select')}
                                    </button>
                                )}
                            </div>
                        </div>

                        {/* Selection mode controls */}
                        {selectionMode && recentJobs.length > 0 && (
                            <div className="flex flex-wrap items-center gap-3 mb-3 p-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]">
                                <label className="flex items-center gap-2 cursor-pointer text-sm">
                                    <input
                                        type="checkbox"
                                        checked={selectedJobIds.size === recentJobs.length && recentJobs.length > 0}
                                        onChange={(e) => {
                                            if (e.target.checked) {
                                                setSelectedJobIds(new Set(recentJobs.map(j => j.id)));
                                            } else {
                                                setSelectedJobIds(new Set());
                                            }
                                        }}
                                        className="w-4 h-4 rounded border-[var(--border)] accent-[var(--accent)]"
                                    />
                                    {selectedJobIds.size === recentJobs.length
                                        ? (t('deselectAll') || 'Deselect All')
                                        : (t('selectAll') || 'Select All')}
                                </label>
                                <span className="text-xs text-[var(--muted)]">
                                    {selectedJobIds.size} {t('selected') || 'selected'}
                                </span>
                                <div className="flex-1" />
                                {confirmBatchDelete ? (
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs text-[var(--danger)]">
                                            {t('deleteSelectedConfirm') || `Delete ${selectedJobIds.size} items?`}
                                        </span>
                                        <button
                                            onClick={async () => {
                                                setIsBatchDeleting(true);
                                                try {
                                                    await api.deleteJobs(Array.from(selectedJobIds));
                                                    if (selectedJob && selectedJobIds.has(selectedJob.id)) {
                                                        onJobSelect(null);
                                                        setShowPreview(false);
                                                    }
                                                    setSelectedJobIds(new Set());
                                                    setConfirmBatchDelete(false);
                                                    setSelectionMode(false);
                                                    await onRefreshJobs();
                                                } catch (err) {
                                                    console.error('Batch delete failed:', err);
                                                } finally {
                                                    setIsBatchDeleting(false);
                                                }
                                            }}
                                            disabled={isBatchDeleting}
                                            className="text-xs px-3 py-1.5 rounded bg-[var(--danger)] text-white hover:bg-[var(--danger)]/80 disabled:opacity-50"
                                        >
                                            {isBatchDeleting ? '...' : (t('confirmDelete') || 'Confirm')}
                                        </button>
                                        <button
                                            onClick={() => setConfirmBatchDelete(false)}
                                            className="text-xs px-3 py-1.5 rounded border border-[var(--border)] hover:bg-white/5"
                                        >
                                            {t('cancel') || 'Cancel'}
                                        </button>
                                    </div>
                                ) : (
                                    <button
                                        onClick={() => setConfirmBatchDelete(true)}
                                        disabled={selectedJobIds.size === 0}
                                        className="text-xs px-3 py-1.5 rounded border border-[var(--danger)] text-[var(--danger)] hover:bg-[var(--danger)]/10 disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        🗑️ {t('deleteSelected') || 'Delete Selected'} ({selectedJobIds.size})
                                    </button>
                                )}
                            </div>
                        )}

                        {recentJobs.length === 0 && (
                            <p className="text-[var(--muted)] text-sm">{t('noRunsYet')}</p>
                        )}
                        <div className="space-y-2">
                            {recentJobs.map((job) => {
                                const publicUrl = buildStaticUrl(job.result_data?.public_url || job.result_data?.video_path);
                                const timestamp = (job.updated_at || job.created_at) * 1000;
                                const isExpired = (Date.now() - timestamp) > 24 * 60 * 60 * 1000;
                                const isSelected = selectedJobIds.has(job.id);

                                return (
                                    <div
                                        key={job.id}
                                        onClick={() => {
                                            if (selectionMode) {
                                                const newSet = new Set(selectedJobIds);
                                                if (isSelected) {
                                                    newSet.delete(job.id);
                                                } else {
                                                    newSet.add(job.id);
                                                }
                                                setSelectedJobIds(newSet);
                                            }
                                        }}
                                        className={`flex flex-wrap sm:flex-nowrap items-center justify-between gap-3 p-3 rounded-lg border ${isSelected
                                            ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                                            : isExpired
                                                ? 'border-[var(--border)]/30 bg-[var(--surface)] text-[var(--muted)]'
                                                : 'border-[var(--border)] bg-[var(--surface-elevated)]'
                                            } transition-colors ${selectionMode ? 'cursor-pointer hover:bg-[var(--accent)]/5' : ''}`}
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
                                            {/* Checkbox for selection mode - Moved to right */}
                                            {selectionMode && (
                                                <input
                                                    type="checkbox"
                                                    checked={isSelected}
                                                    onChange={() => { }} // Handled by onClick of parent
                                                    className="w-4 h-4 rounded border-[var(--border)] accent-[var(--accent)] flex-shrink-0 cursor-pointer"
                                                />
                                            )}
                                            {isExpired ? (
                                                <span className="text-xs bg-[var(--surface)] border border-[var(--border)] px-2 py-1 rounded text-[var(--muted)]">
                                                    {t('expired') || 'Expired'}
                                                </span>
                                            ) : (
                                                <>
                                                    {job.status === 'completed' && publicUrl && !selectionMode && (
                                                        <>
                                                            <a
                                                                className="text-xs btn-primary py-1.5 px-3 h-auto"
                                                                href={publicUrl}
                                                                download={job.result_data?.original_filename || 'processed.mp4'}
                                                            >
                                                                {t('download') || 'Download'}
                                                            </a>
                                                            <button
                                                                onClick={() => { onJobSelect(job); setShowPreview(true); }}
                                                                className="text-xs btn-secondary py-1.5 px-3 h-auto"
                                                            >
                                                                {t('view') || 'View'}
                                                            </button>
                                                        </>
                                                    )}
                                                    {/* Delete button - hide in selection mode */}
                                                    {!selectionMode && (
                                                        confirmDeleteId === job.id ? (
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
                                                        )
                                                    )}
                                                </>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>

                        {/* Pagination Controls */}
                        {totalPages > 1 && (
                            <div className="flex items-center justify-center gap-4 mt-4 pt-4 border-t border-[var(--border)]">
                                <button
                                    onClick={onPrevPage}
                                    disabled={currentPage <= 1}
                                    className="text-sm px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                >
                                    ← {t('previousPage') || 'Previous'}
                                </button>
                                <span className="text-sm text-[var(--muted)]">
                                    {(() => {
                                        const start = (currentPage - 1) * pageSize + 1;
                                        const end = Math.min(currentPage * pageSize, totalJobs);
                                        return t('paginationShowing')
                                            ? t('paginationShowing').replace('{start}', String(start)).replace('{end}', String(end)).replace('{total}', String(totalJobs))
                                            : `Showing ${start}-${end} of ${totalJobs}`;
                                    })()}
                                </span>
                                <button
                                    onClick={onNextPage}
                                    disabled={currentPage >= totalPages}
                                    className="text-sm px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                >
                                    {t('nextPage') || 'Next'} →
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                <VideoModal
                    isOpen={showPreview}
                    onClose={handleClosePreview}
                    videoUrl={videoUrl || ''}
                />
            </div>
        </div>
    );
}
