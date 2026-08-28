import React, { createContext, useContext, useMemo, useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { API_BASE, JobResponse, api } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { Cue } from '@/components/SubtitleOverlay';
import {
    resegmentCues,
    SUBTITLE_POSITION_MAX,
    SUBTITLE_POSITION_MIN,
    updateCueText,
} from '@/lib/subtitleUtils';
import { PreviewPlayerHandle } from '@/components/PreviewPlayer';
import type { LastUsedSettings, TranscribeMode, TranscribeProvider } from './processTypes';
import { resolveConfiguredTranscription } from '@/lib/transcription';
import { buildSubtitleExportFilename } from '@/lib/exportFilename';
import { downloadArtifactWithGrant } from '@/lib/artifactDownload';

export interface ProcessingOptions {
    transcribeMode: TranscribeMode;
    transcribeProvider: TranscribeProvider;
    sourceDurationSeconds?: number | null;
    outputQuality: 'low size' | 'balanced' | 'high quality';
    outputResolution: '1080x1920' | '2160x3840' | '';
    contextPrompt: string;
    subtitle_position: number;
    max_subtitle_lines: number;
    subtitle_color: string;
    shadow_strength: number;
    highlight_style: string;
    subtitle_size: number;
    karaoke_enabled: boolean;
    watermark_enabled: boolean;
}

interface VideoInfo {
    width: number;
    height: number;
    aspectWarning: boolean;
    thumbnailUrl: string | null;
    durationSeconds: number;
}

const LAST_USED_SETTINGS_KEY = 'lastUsedSubtitleSettings';

interface ProcessContextType {
    // Props passed from parent
    selectedFile: File | null;
    onFileSelect: (file: File | null) => void;
    isProcessing: boolean;
    progress: number;
    statusMessage: string;
    error: string;
    onStartProcessing: (options: ProcessingOptions) => Promise<void>;
    onReprocessJob: (sourceJobId: string, options: ProcessingOptions) => Promise<void>;
    onReset: () => void;
    onCancelProcessing?: () => void;
    selectedJob: JobResponse | null;
    onJobSelect: (job: JobResponse | null) => void;
    onRefreshJobs?: () => Promise<void>;
    statusStyles: Record<string, string>;
    buildStaticUrl: (path?: string | null) => string | null;
    hasVideos: boolean;
    hasActiveJob: boolean;
    transcribeMode: TranscribeMode;
    transcribeProvider: TranscribeProvider;

    // Local state
    subtitlePosition: number;
    setSubtitlePosition: (v: number) => void;
    maxSubtitleLines: number;
    setMaxSubtitleLines: (v: number) => void;
    subtitleColor: string;
    setSubtitleColor: (v: string) => void;
    subtitleSize: number;
    setSubtitleSize: (v: number) => void;
    karaokeEnabled: boolean;
    watermarkEnabled: boolean;
    shadowStrength: number;
    activeSidebarTab: 'transcript' | 'styles';
    setActiveSidebarTab: (v: 'transcript' | 'styles') => void;
    videoInfo: VideoInfo | null;
    setVideoInfo: (v: VideoInfo | null) => void;
    previewVideoUrl: string | null;
    setPreviewVideoUrl: (url: string | null) => void;
    videoUrl: string | null;
    cues: Cue[];
    setCues: (cues: Cue[]) => void;
    processedCues: Cue[];

    // Derived/Refs
    fileInputRef: React.RefObject<HTMLInputElement | null>;
    resultsRef: React.RefObject<HTMLDivElement | null>;
    transcriptContainerRef: React.RefObject<HTMLDivElement | null>;
    playerRef: React.RefObject<PreviewPlayerHandle | null>;

    // Step management
    currentStep: number;
    setOverrideStep: (step: number | null) => void;
    overrideStep: number | null;

    // Actions
    handleStart: () => void;
    handleExport: (resolution: string) => Promise<void>;
    exportingResolutions: Record<string, boolean>;
    exportError: string | null;

    // Transcript editing
    editingCueIndex: number | null;
    setEditingCueIndex: (i: number | null) => void;
    editingCueSurface: 'video' | 'transcript' | null;
    editingCueDraft: string;
    setEditingCueDraft: (s: string) => void;
    isSavingTranscript: boolean;
    transcriptLoadError: string | null;
    transcriptSaveError: string | null;
    setTranscriptSaveError: (s: string | null) => void;
    beginEditingCue: (index: number, surface?: 'video' | 'transcript') => void;
    cancelEditingCue: () => void;
    saveEditingCue: () => Promise<void>;
    updateCueText: (cue: Cue, nextText: string) => Cue;
    handleUpdateDraft: (text: string) => void;

    // Constants
    SUBTITLE_COLORS: Array<{ label: string; value: string; ass: string }>;
}

const ProcessContext = createContext<ProcessContextType | undefined>(undefined);

export function useProcessContext() {
    const context = useContext(ProcessContext);
    if (!context) {
        throw new Error('useProcessContext must be used within a ProcessProvider');
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
    onReprocessJob: (sourceJobId: string, options: ProcessingOptions) => Promise<void>;
    onReset: () => void;
    onCancelProcessing?: () => void;
    selectedJob: JobResponse | null;
    onJobSelect: (job: JobResponse | null) => void;
    onRefreshJobs?: () => Promise<void>;
    statusStyles: Record<string, string>;
    buildStaticUrl: (path?: string | null) => string | null;
    totalJobs: number;
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

    // Derived: user has videos if they have at least one completed job in their history
    // Historical availability metadata exposed to account/history surfaces.
    const hasVideos = totalJobs > 0;

    // A processing or selected job unlocks downstream workflow context.
    const hasActiveJob = isProcessing || Boolean(selectedJob);

    const clampNumber = (value: unknown, min: number, max: number): number | null => {
        const num = typeof value === 'number' ? value : Number(value);
        if (!Number.isFinite(num)) return null;
        return Math.max(min, Math.min(max, num));
    };

    // Helper to get initial value from localStorage or default
    const getInitialValue = <T,>(key: keyof LastUsedSettings, defaultValue: T): T => {
        if (typeof window === 'undefined') return defaultValue;
        try {
            const stored = localStorage.getItem(LAST_USED_SETTINGS_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                if (parsed && parsed[key] !== undefined) {
                    const rawValue = parsed[key] as unknown;
                    if (key === 'position') {
                        return (
                            clampNumber(rawValue, SUBTITLE_POSITION_MIN, SUBTITLE_POSITION_MAX)
                            ?? defaultValue
                        ) as T;
                    }
                    if (key === 'size') {
                        return (clampNumber(rawValue, 50, 150) ?? defaultValue) as T;
                    }
                    if (key === 'lines') {
                        return (clampNumber(rawValue, 0, 4) ?? defaultValue) as T;
                    }
                    if (key === 'color') {
                        return (typeof rawValue === 'string' && rawValue.trim() ? rawValue : defaultValue) as T;
                    }
                    return rawValue as T;
                }
            }
        } catch {
            // Ignore errors
        }
        return defaultValue;
    };

    // Public configuration selects only the requested UI route. The backend
    // independently enforces feature flags, provider scope, credentials, and budgets.
    // Missing or invalid configuration always fails closed to the mock engine.
    const configuredTranscription = resolveConfiguredTranscription(
        process.env.NEXT_PUBLIC_TRANSCRIBE_PROVIDER,
        process.env.NEXT_PUBLIC_TRANSCRIBE_MODE,
    );
    const transcribeMode: TranscribeMode = configuredTranscription.mode;
    const transcribeProvider: TranscribeProvider = configuredTranscription.provider;

    // Initial values with priority: LocalStorage > Defaults
    // User-adjustable settings load from localStorage. Advanced output behavior
    // stays fixed so hidden controls cannot leave surprising persisted states.
    const [subtitlePosition, setSubtitlePosition] = useState<number>(() => getInitialValue('position', 20));
    const [maxSubtitleLines, setMaxSubtitleLines] = useState(() => getInitialValue('lines', 2));
    const [subtitleColor, setSubtitleColor] = useState<string>(() => getInitialValue('color', '#FFFF00'));
    const [subtitleSize, setSubtitleSize] = useState<number>(() => getInitialValue('size', 85));
    const karaokeEnabled = true;
    const watermarkEnabled = false;

    const [shadowStrength] = useState<number>(4);

    const [activeSidebarTab, setActiveSidebarTab] = useState<'transcript' | 'styles'>('transcript');

    const [videoInfo, setVideoInfo] = useState<VideoInfo | null>(null);
    const [previewVideoUrl, setPreviewVideoUrl] = useState<string | null>(null);
    const transcriptionSource = selectedJob?.result_data?.transcription_url ?? null;
    const [cueResource, setCueResource] = useState<{
        source: string | null;
        cues: Cue[];
        error: string | null;
    }>({
        source: transcriptionSource,
        cues: [],
        error: null,
    });
    const cues = useMemo(
        () => cueResource.source === transcriptionSource ? cueResource.cues : [],
        [cueResource, transcriptionSource],
    );
    const transcriptLoadError = cueResource.source === transcriptionSource
        ? cueResource.error
        : null;
    const setCues = useCallback((nextCues: Cue[]) => {
        setCueResource({ source: transcriptionSource, cues: nextCues, error: null });
    }, [transcriptionSource]);

    const [overrideStep, setOverrideStepState] = useState<number | null>(null);
    const [exportingResolutions, setExportingResolutions] = useState<Record<string, boolean>>({});
    const [exportError, setExportError] = useState<string | null>(null);

    // Transcript editing state
    const [editingCueIndex, setEditingCueIndex] = useState<number | null>(null);
    const [editingCueSurface, setEditingCueSurface] = useState<'video' | 'transcript' | null>(null);
    const [editingCueDraft, setEditingCueDraft] = useState<string>('');
    const [isSavingTranscript, setIsSavingTranscript] = useState(false);
    const [transcriptSaveError, setTranscriptSaveError] = useState<string | null>(null);
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
        if (selectedJob?.status === 'completed') {
            return 3;
        }
        if (selectedFile || selectedJob || isProcessing) return 2;
        return 1;
    }, [isProcessing, selectedFile, selectedJob]);

    const setOverrideStep = useCallback((step: number | null) => {
        setOverrideStepState(step === calculatedStep ? null : step);
    }, [calculatedStep]);

    const [observedCalculatedStep, setObservedCalculatedStep] = useState(calculatedStep);
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
        setExportError(null);
        setTranscriptSaveError(null);
        setIsSavingTranscript(false);
        setEditingCueIndex(null);
        setEditingCueSurface(null);
        setEditingCueDraft('');
        setOverrideStepState(null);
    }

    const currentStep = overrideStep ?? calculatedStep;

    const videoUrl = useMemo(() => {
        // Don't return a URL if files are marked as missing on the server
        if (selectedJob?.result_data?.files_missing) {
            return null;
        }
        return buildStaticUrl(selectedJob?.result_data?.public_url || selectedJob?.result_data?.video_path);
    }, [buildStaticUrl, selectedJob]);

    const persistSubtitleSettings = useCallback(() => {
        const settings: LastUsedSettings = {
            position: subtitlePosition,
            size: subtitleSize,
            lines: maxSubtitleLines,
            color: subtitleColor,
            timestamp: Date.now(),
        };
        try {
            localStorage.setItem(LAST_USED_SETTINGS_KEY, JSON.stringify(settings));
        } catch {
            // Ignore localStorage errors
        }
    }, [subtitlePosition, subtitleSize, maxSubtitleLines, subtitleColor]);

    // Constants
    const SUBTITLE_COLORS = useMemo(() => [
        { label: t('colorYellow'), value: '#FFFF00', ass: '&H0000FFFF' },
        { label: t('colorPurple'), value: '#8B5CF6', ass: '&H00F65C8B' },
        { label: t('colorCyan'), value: '#00FFFF', ass: '&H00FFFF00' },
        { label: t('colorGreen'), value: '#00FF00', ass: '&H0000FF00' },
        { label: t('colorMagenta'), value: '#FF00FF', ass: '&H00FF00FF' },
    ], [t]);

    // Scroll to results when job completes, BUT only if we are not overriding navigation (e.g. user clicked Step 1/2)
    useEffect(() => {
        if (selectedJob?.status === 'completed' && overrideStep === null) {
            // Small timeout to ensure DOM is ready/expanded
            setTimeout(() => {
                resultsRef.current?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start',
                });
            }, 100);
        }
    }, [selectedJob?.status, overrideStep]);

    const handleStart = useCallback(() => {
        const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];

        if (!selectedFile) {
            if (selectedJob?.status === 'completed') {
                void onReprocessJob(selectedJob.id, {
                    transcribeMode,
                    transcribeProvider,
                    sourceDurationSeconds:
                        videoInfo?.durationSeconds
                        ?? selectedJob.result_data?.duration_seconds
                        ?? null,
                    outputQuality: 'balanced',
                    outputResolution: '',
                    contextPrompt: '',
                    subtitle_position: subtitlePosition,
                    max_subtitle_lines: maxSubtitleLines,
                    subtitle_color: colorObj.ass,
                    shadow_strength: shadowStrength,
                    highlight_style: 'active-graphics',
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
            outputQuality: 'balanced',
            outputResolution: '',
            contextPrompt: '',
            subtitle_position: subtitlePosition,
            max_subtitle_lines: maxSubtitleLines,
            subtitle_color: colorObj.ass,
            shadow_strength: shadowStrength,
            highlight_style: 'active-graphics',
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

    const handleExport = useCallback(async (resolution: string) => {
        if (!selectedJob) return;
        const exportJobId = selectedJob.id;

        setExportError(null);
        setExportingResolutions(prev => ({ ...prev, [resolution]: true }));
        try {
            const subtitleFileFormats = new Set(['srt', 'vtt', 'txt']);
            const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];
            let videoQuality: 'low size' | 'balanced' | undefined;
            if (!subtitleFileFormats.has(resolution)) {
                videoQuality = resolution === '720x1280' ? 'low size' : 'balanced';
            }

            const updatedJob = await api.exportVideo(selectedJob.id, resolution, {
                subtitle_position: subtitlePosition,
                max_subtitle_lines: maxSubtitleLines,
                subtitle_color: colorObj.ass,
                shadow_strength: shadowStrength,
                highlight_style: 'active-graphics',
                subtitle_size: subtitleSize,
                karaoke_enabled: karaokeEnabled,
                watermark_enabled: watermarkEnabled,
                video_quality: videoQuality,
            });
            if (selectedJobIdRef.current !== exportJobId) return;
            onJobSelect(updatedJob);
            void onRefreshJobs?.();

            persistSubtitleSettings();

            if (updatedJob.result_data?.variants?.[resolution]) {
                const artifactPath = updatedJob.result_data.variants[resolution];
                const extension = subtitleFileFormats.has(resolution) ? resolution : 'mp4';
                const downloadFilename = buildSubtitleExportFilename(
                    updatedJob.result_data.original_filename
                        ?? selectedJob.result_data?.original_filename,
                    extension,
                );
                await downloadArtifactWithGrant(
                    selectedJob.id,
                    artifactPath,
                    downloadFilename,
                    buildStaticUrl,
                );
            }
        } catch (err) {
            if (selectedJobIdRef.current === exportJobId) {
                setExportError(
                    err instanceof Error ? err.message : (t('exportVideoError') || 'Failed to export file')
                );
            }
        } finally {
            if (selectedJobIdRef.current === exportJobId) {
                setExportingResolutions(prev => ({ ...prev, [resolution]: false }));
            }
        }
    }, [
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
    ]);

    const beginEditingCue = useCallback((index: number, surface: 'video' | 'transcript' = 'transcript') => {
        setTranscriptSaveError(null);
        setEditingCueIndex(index);
        setEditingCueSurface(surface);
        setEditingCueDraft(cues[index]?.text ?? '');
    }, [cues]);

    const cancelEditingCue = useCallback(() => {
        setTranscriptSaveError(null);
        setEditingCueIndex(null);
        setEditingCueSurface(null);
        setEditingCueDraft('');
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
            setEditingCueDraft('');
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
            setEditingCueDraft('');
        } catch (err) {
            if (selectedJobIdRef.current !== editingJobId) return;
            // Keep the editor and server-backed transcript in sync. If persistence
            // fails, restore the last confirmed cues so exports cannot silently use
            // text that the UI only saved locally.
            setCues(currentCues);
            setTranscriptSaveError(
                err instanceof Error ? err.message : (t('transcriptSaveError') || 'Unable to save transcript')
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

        const resolvedUrl = transcriptionUrl.startsWith('http') ? transcriptionUrl : `${API_BASE}${transcriptionUrl}`;

        fetch(resolvedUrl, { credentials: 'include' })
            .then(res => {
                if (!res.ok) throw new Error('Failed to fetch transcription');
                return res.json();
            })
            .then(data => {
                if (cancelled) return;
                if (!Array.isArray(data)) {
                    throw new Error('Invalid transcription payload');
                }
                setCueResource({ source: transcriptionUrl, cues: data as Cue[], error: null });
            })
            .catch(() => {
                if (!cancelled) {
                    setCueResource({
                        source: transcriptionUrl,
                        cues: [],
                        error: t('transcriptLoadError'),
                    });
                }
            });

        return () => {
            cancelled = true;
        };
    }, [t, transcriptionSource]);

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
        hasVideos,
        hasActiveJob,
        transcribeMode,
        transcribeProvider,
        subtitlePosition, setSubtitlePosition,
        maxSubtitleLines, setMaxSubtitleLines,
        subtitleColor, setSubtitleColor,
        subtitleSize, setSubtitleSize,
        karaokeEnabled,
        watermarkEnabled,
        shadowStrength,
        activeSidebarTab, setActiveSidebarTab,
        videoInfo, setVideoInfo,
        previewVideoUrl, setPreviewVideoUrl,
        videoUrl,
        cues, setCues,
        processedCues,
        fileInputRef, resultsRef, transcriptContainerRef, playerRef,
        currentStep, setOverrideStep, overrideStep,
        handleStart, handleExport, exportingResolutions,
        exportError,
        editingCueIndex, setEditingCueIndex,
        editingCueSurface,
        editingCueDraft, setEditingCueDraft,
        isSavingTranscript, transcriptLoadError, transcriptSaveError, setTranscriptSaveError,
        beginEditingCue, cancelEditingCue, saveEditingCue, updateCueText, handleUpdateDraft,
        SUBTITLE_COLORS,
    };

    return <ProcessContext.Provider value={value}>{children}</ProcessContext.Provider>;
}
