import React, { createContext, useContext, useMemo, useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE, JobResponse, api } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { Cue } from '@/components/SubtitleOverlay';
import { resegmentCues } from '@/lib/subtitleUtils';
import { PreviewPlayerHandle } from '@/components/PreviewPlayer';

export type TranscribeMode = 'standard' | 'pro';
export type TranscribeProvider = 'groq';

export interface ProcessingOptions {
    transcribeMode: TranscribeMode;
    transcribeProvider: TranscribeProvider;
    outputQuality: 'low size' | 'balanced' | 'high quality';
    outputResolution: '1080x1920' | '2160x3840' | '';
    useAI: boolean;
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

interface LastUsedSettings {
    position: number;
    size: number;
    lines: number;
    color: string;
    karaoke: boolean;
    watermark: boolean;
    timestamp: number;
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
    statusStyles: Record<string, string>;
    buildStaticUrl: (path?: string | null) => string | null;
    hasVideos: boolean;
    hasActiveJob: boolean;

    // Local state
    hasChosenModel: boolean;
    setHasChosenModel: (v: boolean) => void;
    transcribeMode: TranscribeMode | null;
    setTranscribeMode: (v: TranscribeMode | null) => void;
    transcribeProvider: TranscribeProvider | null;
    setTranscribeProvider: (v: TranscribeProvider | null) => void;
    subtitlePosition: number;
    setSubtitlePosition: (v: number) => void;
    maxSubtitleLines: number;
    setMaxSubtitleLines: (v: number) => void;
    subtitleColor: string;
    setSubtitleColor: (v: string) => void;
    subtitleSize: number;
    setSubtitleSize: (v: number) => void;
    karaokeEnabled: boolean;
    setKaraokeEnabled: (v: boolean) => void;
    watermarkEnabled: boolean;
    setWatermarkEnabled: (v: boolean) => void;
    shadowStrength: number;
    activeSidebarTab: 'transcript' | 'styles' | 'intelligence';
    setActiveSidebarTab: (v: 'transcript' | 'styles' | 'intelligence') => void;
    activePreset: string | null;
    setActivePreset: (v: string | null) => void;
    videoInfo: { width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null } | null;
    setVideoInfo: (v: { width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null } | null) => void;
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
    saveLastUsedSettings: () => void;
    lastUsedSettings: LastUsedSettings | null;

    // Transcript editing
    editingCueIndex: number | null;
    setEditingCueIndex: (i: number | null) => void;
    editingCueDraft: string;
    setEditingCueDraft: (s: string) => void;
    isSavingTranscript: boolean;
    transcriptSaveError: string | null;
    setTranscriptSaveError: (s: string | null) => void;
    beginEditingCue: (index: number) => void;
    cancelEditingCue: () => void;
    saveEditingCue: () => Promise<void>;
    updateCueText: (cue: Cue, nextText: string) => Cue;
    handleUpdateDraft: (text: string) => void;

    // Constants
    SUBTITLE_COLORS: Array<{ label: string; value: string; ass: string }>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    STYLE_PRESETS: Array<any>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    AVAILABLE_MODELS: Array<any>;
}

const ProcessContext = createContext<ProcessContextType | undefined>(undefined);

const resolveTierFromJob = (
    provider: string | null | undefined,
    model: string | null | undefined,
): TranscribeMode => {
    const normalizedProvider = (provider ?? '').trim().toLowerCase();
    const normalizedModel = (model ?? '').trim().toLowerCase();
    if (normalizedModel === 'pro' || normalizedModel === 'standard') {
        return normalizedModel as TranscribeMode;
    }
    if (normalizedModel.includes('turbo') || normalizedModel.includes('enhanced')) return 'standard';
    if (normalizedModel.includes('large')) return 'pro';
    if (normalizedProvider === 'openai') return 'pro';
    if (normalizedModel.includes('ultimate') || normalizedModel.includes('whisper-1') || normalizedModel.includes('openai')) return 'pro';
    return 'standard';
};

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
    statusStyles,
    buildStaticUrl,
    totalJobs,
}: ProcessProviderProps) {
    const { t } = useI18n();

    // Derived: user has videos if they have at least one completed job in their history
    // For new users (totalJobs === 0), only show Step 1 until they choose a model
    const hasVideos = totalJobs > 0;

    // hasActiveJob is true when there's a job being processed or a completed job selected
    // This controls when Step 3 (PreviewSection) should be shown
    const hasActiveJob = isProcessing || Boolean(selectedJob);

    const clampNumber = (value: unknown, min: number, max: number): number | null => {
        const num = typeof value === 'number' ? value : Number(value);
        if (!Number.isFinite(num)) return null;
        return Math.max(min, Math.min(max, num));
    };

    const parseBoolean = (value: unknown): boolean | null => {
        if (typeof value === 'boolean') return value;
        if (typeof value === 'number') return value !== 0;
        if (typeof value === 'string') {
            const cleaned = value.trim().toLowerCase();
            if (['1', 'true', 'yes', 'on'].includes(cleaned)) return true;
            if (['0', 'false', 'no', 'off'].includes(cleaned)) return false;
        }
        return null;
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
                        return (clampNumber(rawValue, 5, 35) ?? defaultValue) as T;
                    }
                    if (key === 'size') {
                        return (clampNumber(rawValue, 50, 150) ?? defaultValue) as T;
                    }
                    if (key === 'lines') {
                        return (clampNumber(rawValue, 0, 4) ?? defaultValue) as T;
                    }
                    if (key === 'karaoke' || key === 'watermark') {
                        return (parseBoolean(rawValue) ?? defaultValue) as T;
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

    const [hasChosenModel, setHasChosenModel] = useState<boolean>(() => Boolean(selectedFile));
    const [transcribeMode, setTranscribeMode] = useState<TranscribeMode | null>(() =>
        selectedFile ? 'standard' : null
    );
    const [transcribeProvider, setTranscribeProvider] = useState<TranscribeProvider | null>(() =>
        selectedFile ? 'groq' : null
    );

    // Initial values with priority: LocalStorage > Defaults
    // Defaults: Position: 30 (Middle), Size: 85 (Medium), Lines: 2 (Double), Color: Yellow, Karaoke: True
    const [subtitlePosition, setSubtitlePosition] = useState<number>(() => getInitialValue('position', 20));
    const [maxSubtitleLines, setMaxSubtitleLines] = useState(() => getInitialValue('lines', 2));
    const [subtitleColor, setSubtitleColor] = useState<string>(() => getInitialValue('color', '#FFFF00'));
    const [subtitleSize, setSubtitleSize] = useState<number>(() => getInitialValue('size', 85));
    const [karaokeEnabled, setKaraokeEnabled] = useState(() => getInitialValue('karaoke', true));
    const [watermarkEnabled, setWatermarkEnabled] = useState(() => getInitialValue('watermark', false));

    const [shadowStrength] = useState<number>(4);

    const [activeSidebarTab, setActiveSidebarTab] = useState<'transcript' | 'styles' | 'intelligence'>('transcript');
    const [activePreset, setActivePreset] = useState<string | null>(null); // No preset active by default if we load custom settings

    const [videoInfo, setVideoInfo] = useState<{ width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null } | null>(null);
    const [previewVideoUrl, setPreviewVideoUrl] = useState<string | null>(null);
    const [cues, setCues] = useState<Cue[]>([]);

    const [overrideStep, setOverrideStep] = useState<number | null>(null);
    const [exportingResolutions, setExportingResolutions] = useState<Record<string, boolean>>({});

    // Transcript editing state
    const [editingCueIndex, setEditingCueIndex] = useState<number | null>(null);
    const [editingCueDraft, setEditingCueDraft] = useState<string>('');
    const [isSavingTranscript, setIsSavingTranscript] = useState(false);
    const [transcriptSaveError, setTranscriptSaveError] = useState<string | null>(null);

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
            // Check if current settings match the job results
            const jobProvider = selectedJob.result_data?.transcribe_provider;
            const jobModel = selectedJob.result_data?.model_size; // 'standard' | 'pro' (or legacy values)

            const jobTier = resolveTierFromJob(jobProvider, jobModel);
            if (!transcribeMode || jobTier === transcribeMode) {
                return 3;
            }
            // If mismatch, we fallback to Step 2, but we keep the job for history/preview if needed
            return 2;
        }
        if (hasChosenModel) return 2;
        return 1;
    }, [hasChosenModel, selectedJob, transcribeMode]);

    const currentStep = overrideStep ?? calculatedStep;

    const videoUrl = useMemo(() => {
        // Don't return a URL if files are marked as missing on the server
        if (selectedJob?.result_data?.files_missing) {
            return null;
        }
        return buildStaticUrl(selectedJob?.result_data?.public_url || selectedJob?.result_data?.video_path);
    }, [buildStaticUrl, selectedJob]);

    // Last Used Settings State (synced with above, mainly for context access if needed directly)
    const [lastUsedSettings, setLastUsedSettings] = useState<LastUsedSettings | null>(() => {
        if (typeof window === 'undefined') return null;
        try {
            const stored = localStorage.getItem(LAST_USED_SETTINGS_KEY);
            return stored ? JSON.parse(stored) : null;
        } catch {
            return null;
        }
    });

    const saveLastUsedSettings = useCallback(() => {
        const settings: LastUsedSettings = {
            position: subtitlePosition,
            size: subtitleSize,
            lines: maxSubtitleLines,
            color: subtitleColor,
            karaoke: karaokeEnabled,
            watermark: watermarkEnabled,
            timestamp: Date.now(),
        };
        try {
            localStorage.setItem(LAST_USED_SETTINGS_KEY, JSON.stringify(settings));
            setLastUsedSettings(settings);
        } catch {
            // Ignore localStorage errors
        }
    }, [subtitlePosition, subtitleSize, maxSubtitleLines, subtitleColor, karaokeEnabled, watermarkEnabled]);

    // Constants
    const SUBTITLE_COLORS = useMemo(() => [
        { label: t('colorYellow'), value: '#FFFF00', ass: '&H0000FFFF' },
        { label: t('colorWhite'), value: '#FFFFFF', ass: '&H00FFFFFF' },
        { label: t('colorCyan'), value: '#00FFFF', ass: '&H00FFFF00' },
        { label: t('colorGreen'), value: '#00FF00', ass: '&H0000FF00' },
        { label: t('colorMagenta'), value: '#FF00FF', ass: '&H00FF00FF' },
    ], [t]);

    const STYLE_PRESETS = useMemo(() => [
        {
            id: 'tiktok',
            name: t('styleTiktokName'),
            description: t('styleTiktokDesc'),
            emoji: '🔥',
            settings: {
                position: 30,
                size: 100,
                lines: 0,
                color: '#FFFF00',
                karaoke: true,
                watermark: false,
            },
            colorClass: 'from-pink-500 to-orange-500',
        },
        {
            id: 'cinematic',
            name: t('styleCinematicName'),
            description: t('styleCinematicDesc'),
            emoji: '🎬',
            settings: {
                position: 15,
                size: 85,
                lines: 2,
                color: '#FFFFFF',
                karaoke: false,
                watermark: false,
            },
            colorClass: 'from-slate-500 to-zinc-600',
        },
        {
            id: 'podcast',
            name: t('styleMinimalName'),
            description: t('styleMinimalDesc'),
            emoji: '🎙️',
            settings: {
                position: 15,
                size: 70,
                lines: 3,
                color: '#00FFFF',
                karaoke: false,
                watermark: false,
            },
            colorClass: 'from-cyan-500 to-teal-500',
        },
    ], [t]);

    const AVAILABLE_MODELS = useMemo(() => [
        {
            id: 'standard',
            name: t('modelStandardName'),
            description: t('modelStandardDesc'),
            badge: t('modelStandardBadge'),
            badgeColor: 'text-emerald-400 bg-emerald-400/10',
            provider: 'groq',
            mode: 'standard',
            stats: { speed: 5, accuracy: 4, karaoke: true, linesControl: true },
            icon: (selected: boolean) => (
                <div className={`p-2 rounded-lg ${selected ? 'bg-emerald-500/20 text-emerald-200' : 'bg-emerald-500/10 text-emerald-400'} `}>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                    </svg>
                </div>
            ),
            colorClass: (selected: boolean) => selected
                ? 'border-emerald-500 bg-emerald-500/10 ring-1 ring-emerald-500'
                : 'border-[var(--border)] hover:border-emerald-500/50 hover:bg-emerald-500/5'
        },
        {
            id: 'pro',
            name: t('modelProName'),
            description: t('modelProDesc'),
            badge: t('modelProBadge'),
            badgeColor: 'text-amber-300 bg-amber-400/10',
            provider: 'groq',
            mode: 'pro',
            stats: { speed: 4, accuracy: 5, karaoke: true, linesControl: true },
            icon: (selected: boolean) => (
                <div className={`p-2 rounded-lg ${selected ? 'bg-amber-400/20 text-amber-200' : 'bg-amber-400/10 text-amber-300'} `}>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3l2.5 5.5L20 9l-4 4.5L17 20l-5-2.5L7 20l1-6.5L4 9l5.5-.5L12 3z" />
                    </svg>
                </div>
            ),
            colorClass: (selected: boolean) => selected
                ? 'border-amber-400 bg-amber-400/10 ring-1 ring-amber-400'
                : 'border-[var(--border)] hover:border-amber-400/50 hover:bg-amber-400/5'
        },
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
        if (!transcribeMode || !transcribeProvider) {
            setOverrideStep(1);
            try {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            } catch {
            }
            return;
        }

        const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];

        if (!selectedFile) {
            if (selectedJob?.status === 'completed') {
                void onReprocessJob(selectedJob.id, {
                    transcribeMode,
                    transcribeProvider,
                    outputQuality: 'high quality',
                    outputResolution: '',
                    useAI: false,
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

        // Note: Removed immediate scroll to resultsRef here because we want to stay on Step 2 (Upload)
        // to show the progress bar. The scroll to Step 3 now happens automatically upon completion via the effect above.

        onStartProcessing({
            transcribeMode,
            transcribeProvider,
            outputQuality: 'high quality',
            outputResolution: '',
            useAI: false,
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
        watermarkEnabled,
    ]);

    const handleExport = useCallback(async (resolution: string) => {
        if (!selectedJob) return;

        setExportingResolutions(prev => ({ ...prev, [resolution]: true }));
        try {
            const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];

            const updatedJob = await api.exportVideo(selectedJob.id, resolution, {
                subtitle_position: subtitlePosition,
                max_subtitle_lines: maxSubtitleLines,
                subtitle_color: colorObj.ass,
                shadow_strength: shadowStrength,
                highlight_style: 'active-graphics',
                subtitle_size: subtitleSize,
                karaoke_enabled: karaokeEnabled,
                watermark_enabled: watermarkEnabled,
            });
            onJobSelect(updatedJob);

            saveLastUsedSettings();

            if (updatedJob.result_data?.variants?.[resolution]) {
                const url = buildStaticUrl(updatedJob.result_data.variants[resolution]);
                if (url) {
                    try {
                        // Direct download link method - avoids loading entire file into memory (blob)
                        const link = document.createElement('a');
                        // Add download=true query param to force Content-Disposition: attachment
                        link.href = url + (url.includes('?') ? '&' : '?') + 'download=true';
                        const extension = resolution === 'srt' ? 'srt' : 'mp4';
                        link.download = `processed_${resolution}.${extension}`;
                        // NOTE: Don't set target="_blank" - it prevents download attribute from working
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);
                    } catch (err) {
                        console.error('Download failed:', err);
                        window.open(url, '_blank');
                    }
                }
            }
        } catch (err) {
            console.error('Export failed:', err);
        } finally {
            setExportingResolutions(prev => ({ ...prev, [resolution]: false }));
        }
    }, [
        selectedJob,
        onJobSelect,
        buildStaticUrl,
        SUBTITLE_COLORS,
        subtitleColor,
        subtitlePosition,
        maxSubtitleLines,
        shadowStrength,
        subtitleSize,
        karaokeEnabled,
        watermarkEnabled,
        saveLastUsedSettings,
    ]);

    // Transcript Editing Helpers
    const updateCueText = useCallback((cue: Cue, nextText: string): Cue => {
        const normalizedText = nextText.replace(/\s+/g, ' ').trim();
        const tokens = normalizedText.length > 0 ? normalizedText.split(' ') : [];

        if (!tokens.length) {
            return { ...cue, text: '', words: undefined };
        }

        const oldWords = cue.words?.filter(w => w.text.trim().length > 0) ?? [];
        if (!oldWords.length) {
            return { ...cue, text: normalizedText, words: undefined };
        }

        const oldCount = oldWords.length;
        const nextCount = tokens.length;
        const newWords: NonNullable<Cue['words']> = [];

        if (nextCount === oldCount) {
            for (let i = 0; i < oldCount; i += 1) {
                const word = oldWords[i];
                newWords.push({ ...word, text: tokens[i] });
            }
            return { ...cue, text: normalizedText, words: newWords };
        }

        if (nextCount < oldCount) {
            const base = Math.floor(oldCount / nextCount);
            const remainder = oldCount % nextCount;
            let cursor = 0;

            for (let i = 0; i < nextCount; i += 1) {
                const size = base + (i < remainder ? 1 : 0);
                const group = oldWords.slice(cursor, cursor + size);
                cursor += size;
                const first = group[0];
                const last = group[group.length - 1];
                newWords.push({ start: first.start, end: last.end, text: tokens[i] });
            }

            return { ...cue, text: normalizedText, words: newWords };
        }

        const base = Math.floor(nextCount / oldCount);
        const remainder = nextCount % oldCount;
        let tokenCursor = 0;

        for (let i = 0; i < oldCount; i += 1) {
            const segments = base + (i < remainder ? 1 : 0);
            const wordStart = oldWords[i].start;
            const wordEnd = oldWords[i].end;
            const duration = Math.max(0, wordEnd - wordStart);
            const segmentDuration = duration / Math.max(1, segments);

            for (let j = 0; j < segments; j += 1) {
                const start = wordStart + segmentDuration * j;
                const end = j === segments - 1 ? wordEnd : wordStart + segmentDuration * (j + 1);
                newWords.push({ start, end, text: tokens[tokenCursor] });
                tokenCursor += 1;
            }
        }

        return { ...cue, text: normalizedText, words: newWords };
    }, []);

    const beginEditingCue = useCallback((index: number) => {
        setTranscriptSaveError(null);
        setEditingCueIndex(index);
        setEditingCueDraft(cues[index]?.text ?? '');
    }, [cues]);

    const cancelEditingCue = useCallback(() => {
        setTranscriptSaveError(null);
        setEditingCueIndex(null);
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
        setEditingCueIndex(null);
        setEditingCueDraft('');

        if (!selectedJob?.id) return;
        setIsSavingTranscript(true);
        try {
            await api.updateJobTranscription(selectedJob.id, updatedCues);
        } catch (err) {
            setTranscriptSaveError(
                err instanceof Error ? err.message : (t('transcriptSaveError') || 'Unable to save transcript')
            );
        } finally {
            setIsSavingTranscript(false);
        }
    }, [selectedJob?.id, t, updateCueText]);

    const handleUpdateDraft = useCallback((text: string) => {
        setEditingCueDraft(text);
    }, []);

    // Effects
    useEffect(() => {
        if (selectedFile || selectedJob) {
            setHasChosenModel(true);
        }
    }, [selectedFile, selectedJob]);

    // Dev: Auto-load most recent job if no file selected
    const autoLoadAttempted = useRef(false);

    // Mark as attempted if we have a job or file
    useEffect(() => {
        if (selectedFile || selectedJob) {
            autoLoadAttempted.current = true;
        }
    }, [selectedFile, selectedJob]);

    useEffect(() => {
        if (process.env.NODE_ENV === 'development' && !selectedFile && !selectedJob && !autoLoadAttempted.current) {
            // Wait a bit for auth/init
            const timer = setTimeout(() => {
                if (autoLoadAttempted.current) return; // Double check inside timeout

                api.getJobsPaginated(1, 1).then((res) => {
                    if (res.items && res.items.length > 0) {
                        const latestJob = res.items[0];
                        // Only load if it has a video path
                        if (latestJob.result_data?.video_path) {
                            onJobSelect(latestJob);
                            setHasChosenModel(true);
                            autoLoadAttempted.current = true;
                        }
                    }
                }).catch(err => console.error("Dev auto-load failed:", err));
            }, 1000);
            return () => clearTimeout(timer);
        }
    }, [selectedFile, selectedJob, onJobSelect]);

    useEffect(() => {
        setTranscriptSaveError(null);
        setIsSavingTranscript(false);
        setEditingCueIndex(null);
        setEditingCueDraft('');
    }, [selectedJob?.id]);

    useEffect(() => {
        let cancelled = false;
        const transcriptionUrl = selectedJob?.result_data?.transcription_url;

        if (!transcriptionUrl) {
            setCues([]);
            return () => {
                cancelled = true;
            };
        }

        const resolvedUrl = transcriptionUrl.startsWith('http') ? transcriptionUrl : `${API_BASE}${transcriptionUrl}`;

        fetch(resolvedUrl)
            .then(res => {
                if (!res.ok) throw new Error('Failed to fetch transcription');
                return res.json();
            })
            .then(data => {
                if (cancelled) return;
                setCues(data as Cue[]);
            })
            .catch(err => {
                console.error('Error loading transcription cues:', err);
                if (!cancelled) setCues([]);
            });

        return () => {
            cancelled = true;
        };
    }, [selectedJob?.result_data?.transcription_url]);

    const previousCalculatedStep = useRef(calculatedStep);
    useEffect(() => {
        previousCalculatedStep.current = calculatedStep;

        // Only clear override if we naturally land on the EXACT step we overrode.
        // Never force-push the user forward if they are looking at a previous step.
        if (overrideStep !== null && calculatedStep === overrideStep) {
            setOverrideStep(null);
        }
    }, [calculatedStep, overrideStep]);

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
        hasChosenModel, setHasChosenModel,
        transcribeMode, setTranscribeMode,
        transcribeProvider, setTranscribeProvider,
        subtitlePosition, setSubtitlePosition,
        maxSubtitleLines, setMaxSubtitleLines,
        subtitleColor, setSubtitleColor,
        subtitleSize, setSubtitleSize,
        karaokeEnabled, setKaraokeEnabled,
        watermarkEnabled, setWatermarkEnabled,
        shadowStrength,
        activeSidebarTab, setActiveSidebarTab,
        activePreset, setActivePreset,
        videoInfo, setVideoInfo,
        previewVideoUrl, setPreviewVideoUrl,
        videoUrl,
        cues, setCues,
        processedCues,
        fileInputRef, resultsRef, transcriptContainerRef, playerRef,
        currentStep, setOverrideStep, overrideStep,
        handleStart, handleExport, exportingResolutions,
        saveLastUsedSettings, lastUsedSettings,
        editingCueIndex, setEditingCueIndex,
        editingCueDraft, setEditingCueDraft,
        isSavingTranscript, transcriptSaveError, setTranscriptSaveError,
        beginEditingCue, cancelEditingCue, saveEditingCue, updateCueText, handleUpdateDraft,
        SUBTITLE_COLORS, STYLE_PRESETS, AVAILABLE_MODELS,
    };

    return <ProcessContext.Provider value={value}>{children}</ProcessContext.Provider>;
}
