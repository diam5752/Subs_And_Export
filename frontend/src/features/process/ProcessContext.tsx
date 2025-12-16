import React, { createContext, useContext, useMemo, useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE, JobResponse, api } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { Cue } from '@/components/SubtitleOverlay';
import { resegmentCues } from '@/lib/subtitleUtils';
import { PreviewPlayerHandle } from '@/components/PreviewPlayer';

export type TranscribeMode = 'balanced' | 'turbo';
export type TranscribeProvider = 'local' | 'openai' | 'groq' | 'whispercpp';

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
}

interface LastUsedSettings {
    position: number;
    size: number;
    lines: number;
    color: string;
    karaoke: boolean;
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
    onReset: () => void;
    onCancelProcessing?: () => void;
    selectedJob: JobResponse | null;
    onJobSelect: (job: JobResponse | null) => void;
    statusStyles: Record<string, string>;
    buildStaticUrl: (path?: string | null) => string | null;

    // Local state
    hasChosenModel: boolean;
    setHasChosenModel: (v: boolean) => void;
    transcribeMode: TranscribeMode;
    setTranscribeMode: (v: TranscribeMode) => void;
    transcribeProvider: TranscribeProvider;
    setTranscribeProvider: (v: TranscribeProvider) => void;
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
    shadowStrength: number;
    activeSidebarTab: 'transcript' | 'styles';
    setActiveSidebarTab: (v: 'transcript' | 'styles') => void;
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
    currentTime: number;
    setCurrentTime: (t: number) => void;

    // Derived/Refs
    fileInputRef: React.RefObject<HTMLInputElement>;
    resultsRef: React.RefObject<HTMLDivElement>;
    transcriptContainerRef: React.RefObject<HTMLDivElement>;
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
    onReset: () => void;
    onCancelProcessing?: () => void;
    selectedJob: JobResponse | null;
    onJobSelect: (job: JobResponse | null) => void;
    statusStyles: Record<string, string>;
    buildStaticUrl: (path?: string | null) => string | null;
}

export function ProcessProvider({ children, ...props }: ProcessProviderProps) {
    const { t } = useI18n();

    const [hasChosenModel, setHasChosenModel] = useState<boolean>(() => Boolean(props.selectedFile));
    const [transcribeMode, setTranscribeMode] = useState<TranscribeMode | null>(() =>
        props.selectedFile ? 'turbo' : null
    );
    const [transcribeProvider, setTranscribeProvider] = useState<TranscribeProvider | null>(() =>
        props.selectedFile ? 'local' : null
    );

    const [subtitlePosition, setSubtitlePosition] = useState<number>(16);
    const [maxSubtitleLines, setMaxSubtitleLines] = useState(0);
    const [subtitleColor, setSubtitleColor] = useState<string>('#FFFF00');
    const [subtitleSize, setSubtitleSize] = useState<number>(100);
    const [karaokeEnabled, setKaraokeEnabled] = useState(true);
    const [shadowStrength] = useState<number>(4);

    const [activeSidebarTab, setActiveSidebarTab] = useState<'transcript' | 'styles'>('transcript');
    const [activePreset, setActivePreset] = useState<string | null>('tiktok');

    const [videoInfo, setVideoInfo] = useState<{ width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null } | null>(null);
    const [previewVideoUrl, setPreviewVideoUrl] = useState<string | null>(null);
    const [cues, setCues] = useState<Cue[]>([]);
    const [currentTime, setCurrentTime] = useState(0);

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
        if (props.selectedJob?.status === 'completed') return 3;
        if (hasChosenModel) return 2;
        return 1;
    }, [hasChosenModel, props.selectedJob?.status]);

    const currentStep = overrideStep ?? calculatedStep;

    const videoUrl = useMemo(() => {
        return props.buildStaticUrl(props.selectedJob?.result_data?.public_url || props.selectedJob?.result_data?.video_path);
    }, [props]);

    // Last Used Settings
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
            timestamp: Date.now(),
        };
        try {
            localStorage.setItem(LAST_USED_SETTINGS_KEY, JSON.stringify(settings));
            setLastUsedSettings(settings);
        } catch {
            // Ignore localStorage errors
        }
    }, [subtitlePosition, subtitleSize, maxSubtitleLines, subtitleColor, karaokeEnabled]);

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
            badgeColor: 'text-[var(--muted)] bg-[var(--surface)]',
            provider: 'whispercpp',
            mode: 'turbo',
            stats: { speed: 4, accuracy: 3, karaoke: false, linesControl: false },
            icon: (selected: boolean) => (
                <div className={`p-2 rounded-lg ${selected ? 'bg-cyan-500/20 text-cyan-300' : 'bg-cyan-500/10 text-cyan-500'} `}>
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
            stats: { speed: 2, accuracy: 4, karaoke: true, linesControl: true },
            icon: (selected: boolean) => (
                <div className={`p-2 rounded-lg ${selected ? 'bg-amber-500/20 text-amber-300' : 'bg-amber-500/10 text-amber-500'} `}>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                    </svg>
                </div>
            ),
            colorClass: (selected: boolean) => selected
                ? 'border-amber-500 bg-amber-500/10 ring-1 ring-amber-500'
                : 'border-[var(--border)] hover:border-amber-500/50 hover:bg-amber-500/5'
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
                <div className={`p-2 rounded-lg ${selected ? 'bg-purple-500/20 text-purple-300' : 'bg-purple-500/10 text-purple-400'} `}>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                </div>
            ),
            colorClass: (selected: boolean) => selected
                ? 'border-purple-500 bg-purple-500/10 ring-1 ring-purple-500'
                : 'border-[var(--border)] hover:border-purple-500/50 hover:bg-purple-500/5'
        }
    ], [t]);

    const handleStart = useCallback(() => {
        if (!props.selectedFile) return;

        resultsRef.current?.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
        });

        const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];

        if (!transcribeMode || !transcribeProvider) return;

        props.onStartProcessing({
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
        });
    }, [
        SUBTITLE_COLORS,
        karaokeEnabled,
        maxSubtitleLines,
        props,
        shadowStrength,
        subtitleColor,
        subtitlePosition,
        subtitleSize,
        transcribeMode,
        transcribeProvider,
    ]);

    const handleExport = async (resolution: string) => {
        if (!props.selectedJob) return;

        setExportingResolutions(prev => ({ ...prev, [resolution]: true }));
        try {
            const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];

            const updatedJob = await api.exportVideo(props.selectedJob.id, resolution, {
                subtitle_position: subtitlePosition,
                max_subtitle_lines: maxSubtitleLines,
                subtitle_color: colorObj.ass,
                shadow_strength: shadowStrength,
                highlight_style: 'active-graphics',
                subtitle_size: subtitleSize,
                karaoke_enabled: karaokeEnabled,
            });
            props.onJobSelect(updatedJob);

            saveLastUsedSettings();

            if (updatedJob.result_data?.variants?.[resolution]) {
                const url = props.buildStaticUrl(updatedJob.result_data.variants[resolution]);
                if (url) {
                    try {
                        const response = await fetch(url);
                        const blob = await response.blob();
                        const blobUrl = URL.createObjectURL(blob);
                        const link = document.createElement('a');
                        link.href = blobUrl;
                        link.download = `processed_${resolution}.mp4`;
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);
                        URL.revokeObjectURL(blobUrl);
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
    };

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

    const saveEditingCue = useCallback(async () => {
        if (editingCueIndex === null) return;

        setTranscriptSaveError(null);
        const updatedCues = cues.map((cue, index) => {
            if (index !== editingCueIndex) return cue;
            return updateCueText(cue, editingCueDraft);
        });

        setCues(updatedCues);
        setEditingCueIndex(null);
        setEditingCueDraft('');

        if (!props.selectedJob) return;
        setIsSavingTranscript(true);
        try {
            await api.updateJobTranscription(props.selectedJob.id, updatedCues);
        } catch (err) {
            setTranscriptSaveError(
                err instanceof Error ? err.message : (t('transcriptSaveError') || 'Unable to save transcript')
            );
        } finally {
            setIsSavingTranscript(false);
        }
    }, [cues, editingCueDraft, editingCueIndex, props.selectedJob, t, updateCueText]);

    const handleUpdateDraft = useCallback((text: string) => {
        setEditingCueDraft(text);
    }, []);

    // Effects
    useEffect(() => {
        if (props.selectedFile) {
            setHasChosenModel(true);
        }
    }, [props.selectedFile]);

    useEffect(() => {
        setTranscriptSaveError(null);
        setIsSavingTranscript(false);
        setEditingCueIndex(null);
        setEditingCueDraft('');
    }, [props.selectedJob?.id]);

    useEffect(() => {
        let cancelled = false;
        const transcriptionUrl = props.selectedJob?.result_data?.transcription_url;

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
    }, [props.selectedJob?.result_data?.transcription_url]);

    useEffect(() => {
        if (overrideStep && calculatedStep > overrideStep) {
            setOverrideStep(null);
        }
    }, [calculatedStep, overrideStep]);

    const value = {
        ...props,
        hasChosenModel, setHasChosenModel,
        transcribeMode, setTranscribeMode,
        transcribeProvider, setTranscribeProvider,
        subtitlePosition, setSubtitlePosition,
        maxSubtitleLines, setMaxSubtitleLines,
        subtitleColor, setSubtitleColor,
        subtitleSize, setSubtitleSize,
        karaokeEnabled, setKaraokeEnabled,
        shadowStrength,
        activeSidebarTab, setActiveSidebarTab,
        activePreset, setActivePreset,
        videoInfo, setVideoInfo,
        previewVideoUrl, setPreviewVideoUrl,
        videoUrl,
        cues, setCues,
        processedCues,
        currentTime, setCurrentTime,
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
