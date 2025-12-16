import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import Image from 'next/image';
import { api, JobResponse, API_BASE } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { useAppEnv } from '@/context/AppEnvContext';
import { VideoModal } from '@/components/VideoModal';
import { ViralIntelligence } from '@/components/ViralIntelligence';
import { SubtitlePositionSelector } from '@/components/SubtitlePositionSelector';
import { Cue } from '@/components/SubtitleOverlay';
import { PreviewPlayer, PreviewPlayerHandle } from '@/components/PreviewPlayer';
import { PhoneFrame } from '@/components/PhoneFrame';
import { validateVideoAspectRatio } from '@/lib/video';
import { resegmentCues, findCueIndexAtTime } from '@/lib/subtitleUtils';

import { StepIndicator } from './StepIndicator';

type TranscribeMode = 'balanced' | 'turbo';
type TranscribeProvider = 'local' | 'openai' | 'groq' | 'whispercpp';

const LAST_USED_SETTINGS_KEY = 'lastUsedSubtitleSettings';

const SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR: Record<string, string> = {
    '#FFFF00': 'bg-[#FFFF00]',
    '#FFFFFF': 'bg-[#FFFFFF]',
    '#00FFFF': 'bg-[#00FFFF]',
    '#00FF00': 'bg-[#00FF00]',
    '#FF00FF': 'bg-[#FF00FF]',
};

function getSubtitlePreviewBgClass(color: string): string {
    const normalized = color.trim().toUpperCase();
    return SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR[normalized] ?? SUBTITLE_PREVIEW_BG_CLASS_BY_COLOR['#FFFF00'];
}

function getPreviewBottomClass(position: number | string): string {
    const numericPosition = typeof position === 'number' ? position : Number(position);

    if (!Number.isNaN(numericPosition)) {
        if (numericPosition >= 40) return 'bottom-[80%]';
        if (numericPosition <= 15) return 'bottom-[20%]';
        return 'bottom-[50%]';
    }

    if (position === 'top') return 'bottom-[80%]';
    if (position === 'bottom') return 'bottom-[20%]';
    return 'bottom-[50%]';
}

interface LastUsedSettings {
    position: number;
    size: number;
    lines: number;
    color: string;
    karaoke: boolean;
    timestamp: number;
}


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
    statusStyles: Record<string, string>;
    buildStaticUrl: (path?: string | null) => string | null;
}


export interface ProcessingOptions {
    transcribeMode: TranscribeMode;
    transcribeProvider: TranscribeProvider;
    outputQuality: 'low size' | 'balanced' | 'high quality';
    outputResolution: '1080x1920' | '2160x3840' | ''; // empty = keep original
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
    statusStyles,
    buildStaticUrl,
}: ProcessViewProps) {
    const { t } = useI18n();
    const { appEnv } = useAppEnv();
    const showDevTools = appEnv === 'dev';
    const [hasChosenModel, setHasChosenModel] = useState<boolean>(() => Boolean(selectedFile));
    const fileInputRef = useRef<HTMLInputElement>(null);
    const resultsRef = useRef<HTMLDivElement>(null);
    const transcriptContainerRef = useRef<HTMLDivElement>(null);
    const playerRef = useRef<PreviewPlayerHandle>(null);
    const validationRequestId = useRef(0);
    const [currentTime, setCurrentTime] = useState(0);

    const initialSelectionMade = useRef(false);
    const hasAutoStartedRef = useRef(false);

    // Local state for options
    const [showPreview, setShowPreview] = useState(false);

    const [transcribeMode, setTranscribeMode] = useState<TranscribeMode | null>(() =>
        selectedFile ? 'turbo' : null
    );
    const [transcribeProvider, setTranscribeProvider] = useState<TranscribeProvider | null>(() =>
        selectedFile ? 'local' : null
    );
    // outputQuality state removed as it is now always high quality
    // const [outputQuality, setOutputQuality] = useState<'low size' | 'balanced' | 'high quality'>('balanced');
    const [subtitlePosition, setSubtitlePosition] = useState<number>(16); // TikTok preset: middle (16%)
    const [maxSubtitleLines, setMaxSubtitleLines] = useState(0); // TikTok preset: 1 word at a time
    const [subtitleColor, setSubtitleColor] = useState<string>('#FFFF00'); // Default Yellow
    const [activeSidebarTab, setActiveSidebarTab] = useState<'transcript' | 'styles'>('transcript');
    const [subtitleSize, setSubtitleSize] = useState<number>(100); // TikTok preset: 100% (big)
    const [karaokeEnabled, setKaraokeEnabled] = useState(true);
    const [shadowStrength] = useState<number>(4); // Default Normal
    const useAI = false;
    const contextPrompt = '';
    const [videoInfo, setVideoInfo] = useState<{ width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null } | null>(null);
    const [exportingResolutions, setExportingResolutions] = useState<Record<string, boolean>>({});
    const [previewVideoUrl, setPreviewVideoUrl] = useState<string | null>(null);
    const [cues, setCues] = useState<Cue[]>([]);
    const [editingCueIndex, setEditingCueIndex] = useState<number | null>(null);
    const [editingCueDraft, setEditingCueDraft] = useState<string>('');
    const [isSavingTranscript, setIsSavingTranscript] = useState(false);
    const [transcriptSaveError, setTranscriptSaveError] = useState<string | null>(null);
    const [devSampleLoading, setDevSampleLoading] = useState(false);
    const [devSampleError, setDevSampleError] = useState<string | null>(null);

    // Last Used Settings - load from localStorage on mount
    const [lastUsedSettings, setLastUsedSettings] = useState<LastUsedSettings | null>(() => {
        if (typeof window === 'undefined') return null;
        try {
            const stored = localStorage.getItem(LAST_USED_SETTINGS_KEY);
            return stored ? JSON.parse(stored) : null;
        } catch {
            return null;
        }
    });

    // Save settings to localStorage after export
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

    useEffect(() => {
        if (selectedFile) {
            setHasChosenModel(true);
        }
    }, [selectedFile]);

    useEffect(() => {
        setTranscriptSaveError(null);
        setIsSavingTranscript(false);
        setEditingCueIndex(null);
        setEditingCueDraft('');
    }, [selectedJob?.id]);

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

        if (!selectedJob) return;
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
    }, [cues, editingCueDraft, editingCueIndex, selectedJob, t, updateCueText]);

    // Dynamically re-segment cues based on "Max Lines" selection
    const processedCues = useMemo(() => {
        return resegmentCues(cues, maxSubtitleLines, subtitleSize);
    }, [cues, maxSubtitleLines, subtitleSize]);

    // Auto-seek to first subtitle when preview loads
    const hasAutoSeekedRef = useRef(false);
    useEffect(() => {
        // Only trigger when job is completed and cues are available
        if (
            selectedJob?.status === 'completed' &&
            processedCues &&
            processedCues.length > 0 &&
            !hasAutoSeekedRef.current
        ) {
            const firstCueStart = processedCues[0].start;
            // Give slightly more time for the player to mount and video to load
            const timeout = setTimeout(() => {
                if (playerRef.current) {
                    playerRef.current.seekTo(firstCueStart);
                    hasAutoSeekedRef.current = true;
                }
            }, 500);
            return () => clearTimeout(timeout);
        }
    }, [selectedJob?.status, processedCues]);

    // Reset auto-seek flag when new file is selected or job changes
    useEffect(() => {
        hasAutoSeekedRef.current = false;
    }, [selectedFile, selectedJob?.id]);


    // Color Palette
    const SUBTITLE_COLORS = useMemo(() => [
        { label: t('colorYellow'), value: '#FFFF00', ass: '&H0000FFFF' },
        { label: t('colorWhite'), value: '#FFFFFF', ass: '&H00FFFFFF' },
        { label: t('colorCyan'), value: '#00FFFF', ass: '&H00FFFF00' },
        { label: t('colorGreen'), value: '#00FF00', ass: '&H0000FF00' },
        { label: t('colorMagenta'), value: '#FF00FF', ass: '&H00FF00FF' },
    ], [t]);

    // Style Presets
    const STYLE_PRESETS = useMemo(() => [
        {
            id: 'tiktok',
            name: t('styleTiktokName'),
            description: t('styleTiktokDesc'),
            emoji: '🔥',
            settings: {
                position: 30,  // Middle = 30%
                size: 100,  // 100% = big
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
                position: 15,  // Low = 15%
                size: 85,  // 85% = medium
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
                position: 15,  // Low = 15%
                size: 70,  // 70% = small
                lines: 3,
                color: '#00FFFF',
                karaoke: false,
            },
            colorClass: 'from-cyan-500 to-teal-500',
        },
    ], [t]);

    const [activePreset, setActivePreset] = useState<string | null>('tiktok');

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

    // Drag and drop state
    const [isDragOver, setIsDragOver] = useState(false);

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0] || null;
        onFileSelect(file);
    };

    const handleKeyDown = (e: React.KeyboardEvent, callback: () => void) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            callback();
        }
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
                setOverrideStep(null); // Clear override to advance
            }
        }
    }, [isProcessing, onFileSelect]);

    useEffect(() => {
        if (!selectedFile) {
            validationRequestId.current += 1;
            setVideoInfo(null);
            setPreviewVideoUrl(null); // Clear preview URL
            setCues([]); // Clear cues
            return;
        }

        initialSelectionMade.current = false;
        const requestId = ++validationRequestId.current;

        // Create Blob URL for preview
        const blobUrl = URL.createObjectURL(selectedFile);
        setPreviewVideoUrl(blobUrl);
        // Reset cues when new file selected (until transcribed)
        setCues([]);

        validateVideoAspectRatio(selectedFile).then(info => {
            if (requestId === validationRequestId.current) {
                setVideoInfo(info);
            }
        });

        // Cleanup blob URL when component unmounts or file changes
        return () => {
            URL.revokeObjectURL(blobUrl);
        };
    }, [selectedFile]);

    // Effect: Fetch transcription cues if available
    useEffect(() => {
        if (selectedJob?.result_data?.transcription_url) {
            const url = selectedJob.result_data.transcription_url;
            const fullUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;

            fetch(fullUrl)
                .then(res => {
                    if (!res.ok) throw new Error('Failed to fetch transcription');
                    return res.json();
                })
                .then(data => {
                    // Start of cues is "start", "end" in seconds
                    // Backend saves as: [{start: 0.5, end: 2.0, text: "...", words: [...]}]
                    // Our Cue type assumes same structure.
                    setCues(data as Cue[]);
                })
                .catch(err => {
                    console.error("Error loading transcription cues:", err);
                    setCues([]);
                });
        }
    }, [selectedJob?.result_data?.transcription_url]);

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
                onReset();
                const job = await api.loadDevSampleJob();
                onJobSelect(job);
                resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } catch (err) {
                setDevSampleError(err instanceof Error ? err.message : 'Failed to load dev sample');
            } finally {
                setDevSampleLoading(false);
            }
        },
        [devSampleLoading, isProcessing, onJobSelect, onReset]
    );



    // Instant download handler - forces download instead of opening in browser
    const handleDownload = async (url: string, filename: string) => {
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
        }
    };

    // Scroll active cue into view
    useEffect(() => {
        if (activeSidebarTab !== 'transcript') return;
        if (editingCueIndex !== null) return;
        if (!cues || cues.length === 0) return;

        const activeIndex = findCueIndexAtTime(cues, currentTime);

        if (activeIndex !== -1 && transcriptContainerRef.current) {
            const element = document.getElementById(`cue-${activeIndex}`);
            const container = transcriptContainerRef.current;

            if (element) {
                // Calculate position relative to container
                const elementTop = element.offsetTop;
                const elementHeight = element.offsetHeight;
                const containerHeight = container.clientHeight;

                // Scroll to center the element
                const targetScroll = elementTop - (containerHeight / 2) + (elementHeight / 2);

                container.scrollTo({
                    top: targetScroll,
                    behavior: 'smooth'
                });
            }
        }
    }, [activeSidebarTab, cues, currentTime, editingCueIndex]);

    const handleExport = async (resolution: string) => {
        if (!selectedJob) return;

        setExportingResolutions(prev => ({ ...prev, [resolution]: true }));
        try {
            // Resolve color value
            const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];

            const updatedJob = await api.exportVideo(selectedJob.id, resolution, {
                subtitle_position: subtitlePosition,
                max_subtitle_lines: maxSubtitleLines,
                subtitle_color: colorObj.ass,
                shadow_strength: shadowStrength,
                highlight_style: 'active-graphics', // enforce consistently
                subtitle_size: subtitleSize,
                karaoke_enabled: karaokeEnabled,
            });
            onJobSelect(updatedJob);

            // Save settings to localStorage for "Last Used" preset
            saveLastUsedSettings();

            // Auto-trigger download if we have the variant URL now
            if (updatedJob.result_data?.variants?.[resolution]) {
                const url = buildStaticUrl(updatedJob.result_data.variants[resolution]);
                if (url) {
                    handleDownload(url, `processed_${resolution}.mp4`);
                }
            }
        } catch (err) {
            console.error('Export failed:', err);
        } finally {
            setExportingResolutions(prev => ({ ...prev, [resolution]: false }));
        }
    };

    const handleStart = useCallback(() => {
        if (!selectedFile) return;
        setShowPreview(false); // Hide any previous preview

        // Force scroll immediately for better UX
        resultsRef.current?.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
        });

        const colorObj = SUBTITLE_COLORS.find(c => c.value === subtitleColor) || SUBTITLE_COLORS[0];

        if (!transcribeMode || !transcribeProvider) return;

        onStartProcessing({
            transcribeMode,
            transcribeProvider,
            outputQuality: 'high quality',
            outputResolution: '', // Keep original resolution
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
    }, [
        SUBTITLE_COLORS,
        contextPrompt,
        karaokeEnabled,
        maxSubtitleLines,
        onStartProcessing,
        selectedFile,
        shadowStrength,
        subtitleColor,
        subtitlePosition,
        subtitleSize,
        transcribeMode,
        transcribeProvider,
        useAI,
    ]);

    useEffect(() => {
        hasAutoStartedRef.current = false;
    }, [selectedFile]);

    // Auto-start processing when file is selected
    useEffect(() => {
        if (!selectedFile || isProcessing || selectedJob) return;
        if (hasAutoStartedRef.current) return;
        hasAutoStartedRef.current = true;
        handleStart();
    }, [handleStart, isProcessing, selectedFile, selectedJob]);

    const videoUrl = buildStaticUrl(selectedJob?.result_data?.public_url || selectedJob?.result_data?.video_path);

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

    // Handler functions (extracted for testability)
    const handleUploadCardClick = useCallback(() => {
        if (!isProcessing) {
            fileInputRef.current?.click();
        }
    }, [isProcessing]);

    /* istanbul ignore next -- modal handlers tested in E2E */
    const handleClosePreview = useCallback(() => {
        setShowPreview(false);
    }, []);

    // Compute dynamic theme color for upload section interaction
    const activeTheme = useMemo(() => {
        if (transcribeProvider === 'groq') return {
            borderColor: 'border-purple-500/50',
            bgGradient: 'from-purple-500/20 via-transparent to-purple-500/5',
            iconColor: 'text-purple-400',
            glowColor: 'shadow-[0_0_30px_-5px_rgba(168,85,247,0.3)]'
        };
        if (transcribeProvider === 'whispercpp') return {
            borderColor: 'border-cyan-500/50',
            bgGradient: 'from-cyan-500/20 via-transparent to-cyan-500/5',
            iconColor: 'text-cyan-400',
            glowColor: 'shadow-[0_0_30px_-5px_rgba(6,182,212,0.3)]'
        };
        if (transcribeProvider === 'local') return {
            borderColor: 'border-amber-500/50',
            bgGradient: 'from-amber-500/20 via-transparent to-amber-500/5',
            iconColor: 'text-amber-400',
            glowColor: 'shadow-[0_0_30px_-5px_rgba(251,191,36,0.3)]'
        };
        // Default
        return {
            borderColor: 'border-[var(--accent)]/50',
            bgGradient: 'from-[var(--accent)]/20 via-transparent to-[var(--accent-secondary)]/10',
            iconColor: 'text-[var(--accent)]',
            glowColor: 'shadow-[0_0_30px_-5px_rgba(141,247,223,0.3)]'
        };
    }, [transcribeProvider]);

    const selectedModel = useMemo(() =>
        AVAILABLE_MODELS.find(m => m.provider === transcribeProvider && m.mode === transcribeMode),
        [AVAILABLE_MODELS, transcribeProvider, transcribeMode]);

    const [overrideStep, setOverrideStep] = useState<number | null>(null);

    // Determine base progress (technically where we are)
    const calculatedStep = useMemo(() => {
        // Step 3 ONLY when actually completed
        if (selectedJob?.status === 'completed') return 3;
        // Step 2 includes picking a file AND the processing phase
        if (hasChosenModel) return 2;
        return 1;
    }, [hasChosenModel, selectedJob?.status]);

    // Visually active step (user override takes precedence)
    const currentStep = overrideStep ?? calculatedStep;

    // Auto-advance/reset override when state progresses
    useEffect(() => {
        // If we naturally progressed past the override, clear it to show progress
        if (overrideStep && calculatedStep > overrideStep) {
            setOverrideStep(null);
        }
    }, [calculatedStep, overrideStep]);

    const handleStepClick = (step: number, sectionId?: string) => {
        setOverrideStep(step);
        if (sectionId) {
            document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } else if (step === 1) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    };

    const STEPS = [
        {
            id: 1,
            label: t('modelSelectTitle') || 'Pick Model',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                </svg>
            )
        },
        {
            id: 2,
            label: 'Upload',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
            )
        },
        {
            id: 3,
            label: 'Preview',
            icon: (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.818v6.364a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
            )
        }
    ];

    const playerSettings = useMemo(() => ({
        position: subtitlePosition,
        color: subtitleColor,
        fontSize: subtitleSize,
        karaoke: karaokeEnabled,
        maxLines: maxSubtitleLines,
        shadowStrength: shadowStrength
    }), [subtitlePosition, subtitleColor, subtitleSize, karaokeEnabled, maxSubtitleLines, shadowStrength]);

    const handlePlayerTimeUpdate = useCallback((t: number) => {
        setCurrentTime(t);
    }, []);

    const modelGrid = useMemo(() => (
        <div
            role="radiogroup"
            aria-label={t('modelSelectTitle') || 'Pick a Model'}
            className={`grid grid-cols-1 sm:grid-cols-3 gap-3 transition-all duration-300 ${hasChosenModel ? 'opacity-100' : 'animate-slide-down'}`}
        >
            {AVAILABLE_MODELS.map((model) => {
                const isSelected = transcribeProvider === model.provider && transcribeMode === model.mode;

                // Helper for stat bars (5 dots) with accessibility label
                const renderStat = (value: number, label: string, max: number = 5) => (
                    <div className="flex gap-0.5" role="meter" aria-label={`${label}: ${value} out of ${max}`} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
                        {Array.from({ length: max }).map((_, i) => (
                            <div
                                key={i}
                                className={`h-1.5 w-full rounded-full transition-colors ${i < value
                                    ? (isSelected ? 'bg-current opacity-80' : 'bg-[var(--foreground)] opacity-60')
                                    : 'bg-[var(--foreground)] opacity-20'
                                    } `}
                            />
                        ))}
                    </div>
                );

                return (
                    <button
                        key={model.id}
                        role="radio"
                        aria-checked={isSelected}
                        data-testid={`model-${model.provider === 'local' ? 'turbo' : model.provider}`}
                        onClick={(e) => {
                            e.stopPropagation();
                            // Select model
                            setTranscribeProvider(model.provider as TranscribeProvider);
                            setTranscribeMode(model.mode as TranscribeMode);
                            setHasChosenModel(true);
                            setOverrideStep(2); // Explicitly advance to Step 2 visual

                            // Only scroll if we were not already selected (to avoid jarring jumps if just clicking around)
                            if (!isSelected) {
                                // Auto-scroll to upload section
                                setTimeout(() => {
                                    document.getElementById('upload-section')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                }, 100);
                            }
                        }}
                        className={`p-4 rounded-xl border text-left transition-all duration-300 relative overflow-hidden group flex flex-col h-full ${isSelected
                            ? `${model.colorClass(true)} scale-[1.02] shadow-lg ring-1`
                            : hasChosenModel
                                ? 'border-[var(--border)] opacity-60 hover:opacity-100 hover:scale-[1.01] hover:bg-[var(--surface-elevated)] grayscale hover:grayscale-0' // Dimmed but interactive
                                : model.colorClass(false)
                            }`}
                    >
                        <div className="flex items-start justify-between mb-2 w-full">
                            {model.icon(isSelected)}
                            {isSelected && (
                                <div
                                    className={`w-5 h-5 rounded-full flex items-center justify-center ${model.provider === 'groq'
                                        ? 'bg-purple-500'
                                        : model.provider === 'whispercpp'
                                            ? 'bg-cyan-500'
                                            : 'bg-[var(--accent)]'
                                        }`}
                                >
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
                                {renderStat(model.stats.speed, t('statSpeed'))}
                            </div>
                            <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statAccuracy')}</span>
                                {renderStat(model.stats.accuracy, t('statAccuracy'))}
                            </div>
                            <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statKaraoke')}</span>
                                <div className={`text-[10px] font-bold ${model.stats.karaoke ? 'text-emerald-500' : 'text-[var(--muted)]'} `}>
                                    {model.stats.karaoke ? t('statKaraokeSupported') : t('statKaraokeNo')}
                                </div>
                            </div>
                            <div className="grid grid-cols-[60px,1fr] items-center gap-2">
                                <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{t('statLines')}</span>
                                <div className={`text-[10px] font-bold ${model.stats.linesControl ? 'text-emerald-500' : 'text-cyan-400'} `}>
                                    {model.stats.linesControl ? t('statLinesCustom') : t('statLinesAuto')}
                                </div>
                            </div>
                        </div>

                        <div className="flex items-center gap-2 text-xs pt-3 border-t border-[var(--border)]/50">
                            <span className={`px-2 py-0.5 rounded-full font-medium ${model.badgeColor} `}>
                                {model.badge}
                            </span>
                        </div>
                    </button>
                );
            })}
        </div>
    ), [AVAILABLE_MODELS, transcribeProvider, transcribeMode, hasChosenModel, t]);

    return (
        <div className="grid grid-cols-1 xl:grid-cols-[1.05fr,0.95fr] gap-6">
            <div className="col-span-1 xl:col-span-2">
                <StepIndicator currentStep={currentStep} steps={STEPS} />
            </div>

            <div className="space-y-4">
                {(
                    <div className="card space-y-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div
                                className={`flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 1 ? 'opacity-40 grayscale blur-[1px] hover:opacity-80 hover:grayscale-0 hover:blur-0' : 'opacity-100 scale-[1.01]'}`}
                                onClick={() => handleStepClick(1)}
                            >
                                <span className={`flex items-center justify-center px-4 py-1.5 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 ${currentStep === 1
                                    ? 'bg-[var(--accent)] border-[var(--accent)] text-white shadow-[0_0_20px_2px_var(--accent)] scale-105 ring-2 ring-[var(--accent)]/30'
                                    : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)] group-hover/step:border-[var(--accent)]/50 group-hover/step:text-[var(--accent)]'
                                    }`}>STEP 1</span>
                                <div>
                                    <h3 className="text-xl font-semibold">{t('modelSelectTitle') || 'Pick a Model'}</h3>
                                    {!hasChosenModel && (
                                        <p className="text-sm text-[var(--muted)] mt-1 ml-0.5">{t('modelSelectSubtitle')}</p>
                                    )}
                                </div>
                            </div>
                            {hasChosenModel ? (
                                <span className="inline-flex items-center gap-2 text-xs font-semibold px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
                                    <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                                    {t('statusSynced') || 'Selected'}
                                </span>
                            ) : (
                                <span className="inline-flex items-center gap-2 text-xs font-semibold px-3 py-1 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-200">
                                    <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
                                    {t('statusIdle') || 'Select to continue'}
                                </span>
                            )}
                        </div>

                        {/* Model Grid */}
                        {modelGrid}
                    </div>
                )}

                {/* STEP 2: Upload Video */}
                {!selectedFile && (
                    <div id="upload-section" className={`space-y-4 animate-fade-in-up-scale transition-opacity duration-300 ${!hasChosenModel ? 'opacity-40 pointer-events-none' : ''}`}>
                        <div
                            className={`mb-2 flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 2 ? 'opacity-40 grayscale blur-[1px] hover:opacity-80 hover:grayscale-0 hover:blur-0' : 'opacity-100 scale-[1.01]'}`}
                            onClick={() => handleStepClick(2, 'upload-section')}
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


                        {/* Upload Card */}
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
                                        {/* Model Icon Badge - only show when model is selected */}
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
                                        {/* Model Icon Badge - only show when model is selected */}
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
                )}

                {/* STEP 2: Compact Upload Review (only when file selected - replaces dropzone) */}
                {selectedFile && (
                    <div id="upload-section-compact" className="space-y-4 animate-fade-in-up-scale">
                        <div
                            className={`mb-2 flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 2 ? 'opacity-40 grayscale blur-[1px] hover:opacity-80 hover:grayscale-0 hover:blur-0' : 'opacity-100 scale-[1.01]'}`}
                            onClick={() => handleStepClick(2, 'upload-section-compact')}
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
                                ) : (
                                    <div className="h-full w-full flex items-center justify-center bg-emerald-900/20">
                                        <svg className="w-8 h-8 text-emerald-500/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M15 10l4.553-2.276A1 1 0 0121 8.818v6.364a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                        </svg>
                                    </div>
                                )}

                                {/* Centered Green Tick Overlay */}
                                <div className="absolute inset-0 flex items-center justify-center">
                                    <div className="w-8 h-8 rounded-full bg-emerald-500/80 shadow-lg shadow-emerald-500/40 flex items-center justify-center text-white transform scale-100 group-hover:scale-110 transition-transform backdrop-blur-[1px]">
                                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                        </svg>
                                    </div>
                                </div>
                            </div>

                            {/* File Info */}
                            <div className="flex-1 min-w-0">
                                <h4 className="text-sm font-semibold text-[var(--foreground)] truncate" title={selectedFile.name}>
                                    {selectedFile.name}
                                </h4>
                                <p className="text-xs text-[var(--muted)] flex items-center gap-1.5 mt-0.5">
                                    <span>{(selectedFile.size / (1024 * 1024)).toFixed(1)} MB</span>
                                    <span className="w-1 h-1 rounded-full bg-[var(--border)]" />
                                    {isProcessing ? (
                                        <span className="text-amber-400 font-medium animate-pulse">Processing...</span>
                                    ) : (
                                        <span className="text-emerald-500 font-medium">Ready</span>
                                    )}
                                </p>
                            </div>

                            {/* Actions */}
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onFileSelect(null);
                                    setHasChosenModel(true);
                                }}
                                className="px-3 py-1.5 text-xs font-medium rounded-lg border border-[var(--border)] hover:bg-[var(--surface-elevated)] hover:text-[var(--foreground)] text-[var(--muted)] transition-colors"
                            >
                                Change
                            </button>
                        </div>
                    </div>
                )}

                {error && (
                    <div className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)] animate-fade-in">
                        {error}
                    </div>
                )}

                {/* ACTION BAR: Start Processing */}
                {hasChosenModel && selectedFile && !isProcessing && selectedJob?.status !== 'completed' && (
                    <div className="flex justify-end pt-8 pb-4 animate-fade-in">
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                handleStart();
                            }}
                            disabled={isProcessing || !selectedFile}
                            className={`btn-primary w-full py-4 text-base shadow-lg transition-all ${selectedFile
                                ? 'shadow-[var(--accent)]/20 hover:shadow-[var(--accent)]/40 hover:-translate-y-0.5'
                                : 'opacity-50 cursor-not-allowed grayscale'
                                }`}
                        >
                            <span className="mr-2">✨</span>
                            {t('controlsStart') || 'Generate Video'}
                        </button>
                    </div>
                )}

                <div id="preview-section" className={`space-y-4 scroll-mt-[100px] transition-all duration-500 ${!selectedJob && !isProcessing ? 'opacity-50 grayscale' : ''}`} ref={resultsRef}>

                    <div
                        className={`mb-2 flex items-center gap-4 transition-all duration-300 cursor-pointer group/step ${currentStep !== 3 ? 'opacity-40 grayscale blur-[1px] hover:opacity-80 hover:grayscale-0 hover:blur-0' : 'opacity-100 scale-[1.01]'}`}
                        onClick={() => handleStepClick(3, 'preview-section')}
                    >
                        <span className={`flex items-center justify-center px-4 py-1.5 rounded-full border font-mono text-sm font-bold tracking-widest shadow-sm transition-all duration-500 ${currentStep === 3
                            ? 'bg-[var(--accent)] border-[var(--accent)] text-white shadow-[0_0_20px_2px_var(--accent)] scale-105 ring-2 ring-[var(--accent)]/30'
                            : 'bg-[var(--surface-elevated)] border-[var(--border)] text-[var(--muted)] group-hover/step:border-[var(--accent)]/50 group-hover/step:text-[var(--accent)]'
                            }`}>STEP 3</span>
                        <h3 className="text-xl font-semibold">Preview & Export</h3>
                    </div>

                    <div className="card space-y-4 min-h-[200px]">
                        {(!(isProcessing || (selectedJob && selectedJob.status !== 'pending'))) ? (
                            <div className="py-20 flex flex-col items-center justify-center text-center text-[var(--muted)] border-2 border-dashed border-[var(--border)]/50 rounded-xl bg-[var(--surface-elevated)]/30">
                                <div className="text-5xl mb-4 opacity-20">🎬</div>
                                <p className="font-semibold text-lg opacity-60">Result Preview</p>
                                <p className="text-sm mt-1 opacity-40 max-w-[200px]">Generate a video to see the preview and export options here</p>
                            </div>
                        ) : (
                            <>
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                    <div className="min-w-0 flex-1">
                                        <h3 className="text-2xl font-semibold break-words [overflow-wrap:anywhere]">
                                            {selectedJob?.result_data?.original_filename || (isProcessing ? t('statusProcessingEllipsis') : 'Live Preview')}
                                        </h3>
                                        <p className="text-sm text-[var(--muted)]">{t('liveOutputSubtitle')}</p>
                                    </div>

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
                                                style={{ width: `${progress}% ` }}
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

                                {!isProcessing && selectedJob && selectedJob.status === 'completed' ? (
                                    <div className="animate-fade-in relative">
                                        {/* Animated shimmer border */}
                                        <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-r from-[var(--accent)] via-[var(--accent-secondary)] to-[var(--accent)] bg-[length:200%_100%] animate-shimmer opacity-80" />

                                        {/* Inner glow */}
                                        <div className="preview-card-glow absolute inset-0 rounded-2xl" />

                                        <div className="relative rounded-2xl border border-white/10 bg-[var(--surface-elevated)] overflow-hidden">
                                            {/* Success badge */}


                                            <div className="flex flex-col lg:flex-row gap-6 transition-all duration-500 ease-in-out lg:h-[850px]">
                                                {/* Preview Player Area - Left (Flexible) */}
                                                <div className="flex-1 bg-black/20 rounded-2xl border border-white/5 flex items-center justify-center p-4 lg:p-8 relative overflow-hidden backdrop-blur-sm min-h-0 min-w-0 transition-all duration-500">
                                                    {/* Model Used Indicator - Floating top-left */}
                                                    {(selectedJob?.result_data?.transcribe_provider || transcribeProvider) && (
                                                        <div className="absolute top-4 left-4 z-10 flex items-center gap-2 px-3 py-1.5 rounded-full bg-black/60 border border-white/10 backdrop-blur-md">
                                                            {selectedModel && (
                                                                <span className="text-sm">{selectedModel.icon(true)}</span>
                                                            )}
                                                            <span className="text-xs font-medium text-white/80">
                                                                {(() => {
                                                                    const provider = selectedJob?.result_data?.transcribe_provider || transcribeProvider;
                                                                    if (provider === 'local') return 'Standard';
                                                                    if (provider === 'groq') return 'Enhanced';
                                                                    if (provider === 'openai') return 'Ultimate';
                                                                    return provider;
                                                                })()}
                                                            </span>
                                                        </div>
                                                    )}
                                                    <div className="relative h-[min(70dvh,600px)] w-auto aspect-[9/16] max-w-full shadow-2xl transition-all duration-500 hover:scale-[1.01] lg:h-[90%] lg:max-h-[600px]">
                                                        <PhoneFrame className="w-full h-full" showSocialOverlays={false}>
                                                            {processedCues && processedCues.length > 0 ? (
                                                                <PreviewPlayer
                                                                    ref={playerRef}
                                                                    videoUrl={videoUrl || ''}
                                                                    cues={processedCues}
                                                                    settings={playerSettings}
                                                                    onTimeUpdate={handlePlayerTimeUpdate}
                                                                />
                                                            ) : (
                                                                // Fallback / Loading state
                                                                <div className="relative group w-full h-full flex items-center justify-center bg-gray-900">
                                                                    {videoUrl ? (
                                                                        <video
                                                                            src={`${videoUrl}#t=0.5`}
                                                                            className="absolute inset-0 w-full h-full object-cover opacity-30 blur-sm"
                                                                            muted
                                                                            playsInline
                                                                        />
                                                                    ) : null}
                                                                    <div className="relative z-10 text-center p-6">
                                                                        <div className="mb-3 text-4xl animate-bounce">👆</div>
                                                                        <p className="text-sm font-medium text-white/90">{t('clickToPreview') || 'Preview Pending...'}</p>
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </PhoneFrame>
                                                    </div>
                                                </div>

                                                {/* Sidebar Controls - Right (Fixed Width) */}
                                                <div className="w-full md:w-[500px] lg:w-[600px] flex flex-col bg-[var(--surface)] border border-[var(--border)] rounded-xl shadow-xl overflow-hidden transition-all duration-500">

                                                    {/* Status Header */}
                                                    <div className="p-4 border-b border-[var(--border)] flex items-center justify-between bg-[var(--surface-elevated)]">
                                                        <div className="flex items-center gap-3 overflow-hidden">
                                                            <div className={`w-2.5 h-2.5 rounded-full shrink-0 animate-pulse ${isProcessing ? 'bg-amber-400' : 'bg-emerald-400'}`} />
                                                            <h3 className="font-semibold text-[var(--foreground)] truncate" title={selectedJob.result_data?.original_filename || undefined}>
                                                                {selectedJob.result_data?.original_filename || t('processedVideoFallback')}
                                                            </h3>
                                                        </div>
                                                        {isProcessing && (
                                                            <span className="text-xs font-mono text-amber-400">{progress}%</span>
                                                        )}
                                                    </div>

                                                    <div ref={transcriptContainerRef} className="p-4 sm:p-6 flex-1 flex flex-col min-h-0 custom-scrollbar relative lg:overflow-y-auto">

                                                        {/* Sidebar Tabs */}
                                                        <div className="flex items-center gap-1 p-1 bg-[var(--surface-elevated)] rounded-lg border border-[var(--border)] mb-4">
                                                            <button
                                                                onClick={() => setActiveSidebarTab('transcript')}
                                                                className={`flex-1 py-1.5 px-3 rounded-md text-xs font-medium transition-all ${activeSidebarTab === 'transcript'
                                                                    ? 'bg-[var(--accent)] text-[#031018] shadow-sm'
                                                                    : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/5'
                                                                    }`}
                                                            >
                                                                {t('tabTranscript') || 'Transcript'}
                                                            </button>
                                                            <button
                                                                onClick={() => setActiveSidebarTab('styles')}
                                                                className={`flex-1 py-1.5 px-3 rounded-md text-xs font-medium transition-all ${activeSidebarTab === 'styles'
                                                                    ? 'bg-[var(--accent)] text-[#031018] shadow-sm'
                                                                    : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/5'
                                                                    }`}
                                                            >
                                                                {t('tabStyles') || 'Styles'}
                                                            </button>
                                                        </div>

                                                        {/* Tab Content */}
                                                        <div className="space-y-2 pr-1">
                                                            {activeSidebarTab === 'transcript' ? (
                                                                <>
                                                                    {transcriptSaveError && (
                                                                        <div className="rounded-lg border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-3 py-2 text-xs text-[var(--danger)]">
                                                                            {transcriptSaveError}
                                                                        </div>
                                                                    )}
                                                                    {isSavingTranscript && (
                                                                        <div className="flex items-center gap-2 px-1 text-xs text-[var(--muted)]">
                                                                            <span className="animate-spin">⏳</span>
                                                                            {t('transcriptSaving') || 'Saving…'}
                                                                        </div>
                                                                    )}
                                                                    {cues.map((cue, index) => {
                                                                        const isActive = currentTime >= cue.start && currentTime < cue.end;
                                                                        const isEditing = editingCueIndex === index;
                                                                        const canEditThis = !isSavingTranscript && (editingCueIndex === null || isEditing);

                                                                        return (
                                                                            <div
                                                                                key={`${cue.start}-${cue.end}-${index}`}
                                                                                id={`cue-${index}`}
                                                                                className={`rounded-lg border px-2 py-2 transition-colors ${isActive
                                                                                    ? 'border-[var(--accent)]/25 bg-[var(--accent)]/10'
                                                                                    : 'border-transparent hover:bg-white/5'
                                                                                    }`}
                                                                            >
                                                                                <div className="flex items-start gap-3">
                                                                                    <button
                                                                                        type="button"
                                                                                        onClick={() => playerRef.current?.seekTo(cue.start)}
                                                                                        className="font-mono text-xs opacity-60 pt-0.5 min-w-[42px] text-left hover:opacity-90 transition-opacity"
                                                                                    >
                                                                                        {Math.floor(cue.start / 60)}:{(cue.start % 60).toFixed(0).padStart(2, '0')}
                                                                                    </button>
                                                                                    <div className="flex-1 min-w-0">
                                                                                        {isEditing ? (
                                                                                            <textarea
                                                                                                value={editingCueDraft}
                                                                                                onChange={(e) => setEditingCueDraft(e.target.value)}
                                                                                                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]/70 px-3 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 min-h-[72px] resize-y"
                                                                                                disabled={isSavingTranscript}
                                                                                            />
                                                                                        ) : (
                                                                                            <button
                                                                                                type="button"
                                                                                                onClick={() => playerRef.current?.seekTo(cue.start)}
                                                                                                className={`w-full text-left text-sm break-words [overflow-wrap:anywhere] ${isActive
                                                                                                    ? 'text-[var(--foreground)] font-medium'
                                                                                                    : 'text-[var(--muted)] hover:text-[var(--foreground)]'
                                                                                                    }`}
                                                                                            >
                                                                                                {cue.text}
                                                                                            </button>
                                                                                        )}
                                                                                    </div>
                                                                                    <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">
                                                                                        {isEditing ? (
                                                                                            <>
                                                                                                <button
                                                                                                    type="button"
                                                                                                    onClick={saveEditingCue}
                                                                                                    disabled={isSavingTranscript}
                                                                                                    className="px-2 py-1 rounded-md text-xs font-semibold bg-emerald-500/15 text-emerald-200 border border-emerald-500/25 hover:bg-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                                                                                                >
                                                                                                    {isSavingTranscript ? (t('transcriptSaving') || 'Saving…') : (t('transcriptSave') || 'Save')}
                                                                                                </button>
                                                                                                <button
                                                                                                    type="button"
                                                                                                    onClick={cancelEditingCue}
                                                                                                    disabled={isSavingTranscript}
                                                                                                    className="px-2 py-1 rounded-md text-xs font-medium bg-white/5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 border border-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
                                                                                                >
                                                                                                    {t('transcriptCancel') || 'Cancel'}
                                                                                                </button>
                                                                                            </>
                                                                                        ) : (
                                                                                            <button
                                                                                                type="button"
                                                                                                onClick={() => beginEditingCue(index)}
                                                                                                disabled={!canEditThis}
                                                                                                className="px-2 py-1 rounded-md text-xs font-medium bg-white/5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 border border-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
                                                                                            >
                                                                                                {t('transcriptEdit') || 'Edit'}
                                                                                            </button>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            </div>
                                                                        );
                                                                    })}
                                                                    {cues.length === 0 && (
                                                                        <div className="text-center text-[var(--muted)] py-10 opacity-50">
                                                                            {t('liveOutputStatusIdle') || 'Transcript will appear here...'}
                                                                        </div>
                                                                    )}
                                                                </>
                                                            ) : (
                                                                <div className="animate-fade-in pr-2">
                                                                    {/* Style Presets Grid (Moved from Step 3) */}
                                                                    <div className="grid grid-cols-2 gap-3 mb-6">
                                                                        {STYLE_PRESETS.map((preset) => {
                                                                            return (
                                                                                <button
                                                                                    key={preset.id}
                                                                                    role="radio"
                                                                                    aria-checked={activePreset === preset.id}
                                                                                    aria-label={preset.name}
                                                                                    onClick={(e) => {
                                                                                        e.stopPropagation();
                                                                                        setActivePreset(preset.id);
                                                                                        setSubtitlePosition(preset.settings.position);
                                                                                        setSubtitleSize(preset.settings.size);
                                                                                        setMaxSubtitleLines(preset.settings.lines);
                                                                                        setSubtitleColor(preset.settings.color);
                                                                                        setKaraokeEnabled(preset.settings.karaoke);
                                                                                    }}
                                                                                    className={`p-3 rounded-xl border text-left transition-all relative overflow-hidden group flex flex-row gap-3 items-center ${activePreset === preset.id
                                                                                        ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]'
                                                                                        : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                                                        } `}
                                                                                >
                                                                                    {/* Gradient background */}
                                                                                    <div className={`absolute inset-0 bg-gradient-to-br ${preset.colorClass} opacity-10`} />

                                                                                    {/* Vertical Phone Preview (9:16 aspect ratio) */}
                                                                                    <div className="flex-shrink-0 w-10 aspect-[9/16] bg-slate-900 rounded-lg border border-slate-600 overflow-hidden relative shadow-lg">
                                                                                        {/* Phone notch */}
                                                                                        <div className="absolute top-1 left-1/2 -translate-x-1/2 w-4 h-1 bg-slate-700 rounded-full" />
                                                                                        {/* Screen content */}
                                                                                        <div className="absolute inset-0 bg-gradient-to-b from-slate-800/50 to-black/60" />
                                                                                        {/* Subtitle lines */}
                                                                                        <div className={`absolute left-1 right-1 flex flex-col gap-[1px] items-center ${getPreviewBottomClass(preset.settings.position)}`}>
                                                                                            <div className={`h-[2px] w-[75%] rounded-full ${getSubtitlePreviewBgClass(preset.settings.color)}`} />
                                                                                            {preset.settings.lines > 1 && (
                                                                                                <div className={`h-[2px] w-[55%] rounded-full ${getSubtitlePreviewBgClass(preset.settings.color)}`} />
                                                                                            )}
                                                                                        </div>
                                                                                        {/* Home indicator */}
                                                                                        <div className="absolute bottom-1 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-slate-600 rounded-full" />
                                                                                    </div>

                                                                                    {/* Text content */}
                                                                                    <div className="flex-1 min-w-0 relative">
                                                                                        <div className="flex items-center gap-1.5 mb-0.5">
                                                                                            <span className="text-sm">{preset.emoji}</span>
                                                                                            <span className="font-semibold text-xs truncate">{preset.name}</span>
                                                                                        </div>
                                                                                        <p className="text-[10px] text-[var(--muted)] leading-tight line-clamp-2">{preset.description}</p>
                                                                                    </div>

                                                                                    {activePreset === preset.id && (
                                                                                        <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-[var(--accent)] flex items-center justify-center animate-scale-in">
                                                                                            <svg className="w-2.5 h-2.5 text-[#031018]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                                                                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                                                                            </svg>
                                                                                        </div>
                                                                                    )}
                                                                                </button>
                                                                            );
                                                                        })}

                                                                        {/* Last Used Tile */}
                                                                        <button
                                                                            role="radio"
                                                                            aria-checked={activePreset === 'lastUsed'}
                                                                            aria-label={t('styleLastUsedName') || 'Last Used'}
                                                                            aria-disabled={!lastUsedSettings}
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                if (!lastUsedSettings) return;
                                                                                setActivePreset('lastUsed');
                                                                                setSubtitlePosition(lastUsedSettings.position);
                                                                                setSubtitleSize(lastUsedSettings.size);
                                                                                setMaxSubtitleLines(lastUsedSettings.lines);
                                                                                setSubtitleColor(lastUsedSettings.color);
                                                                                setKaraokeEnabled(lastUsedSettings.karaoke);
                                                                            }}
                                                                            className={`p-3 rounded-xl border text-left transition-all relative overflow-hidden group flex flex-row gap-3 items-center ${activePreset === 'lastUsed'
                                                                                ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]'
                                                                                : !lastUsedSettings
                                                                                    ? 'border-[var(--border)] opacity-50 grayscale cursor-not-allowed'
                                                                                    : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                                                                } `}
                                                                            disabled={!lastUsedSettings}
                                                                        >
                                                                            {/* Gradient background */}
                                                                            <div className="absolute inset-0 bg-gradient-to-br from-emerald-500 to-teal-600 opacity-10" />

                                                                            {/* Vertical Phone Preview (9:16 aspect ratio) */}
                                                                            <div className="flex-shrink-0 w-10 aspect-[9/16] bg-slate-900 rounded-lg border border-slate-600 overflow-hidden relative shadow-lg">
                                                                                {/* Phone notch */}
                                                                                <div className="absolute top-1 left-1/2 -translate-x-1/2 w-4 h-1 bg-slate-700 rounded-full" />
                                                                                {/* Screen content */}
                                                                                <div className="absolute inset-0 bg-gradient-to-b from-slate-800/50 to-black/60" />
                                                                                {lastUsedSettings ? (
                                                                                    <>
                                                                                        {/* Subtitle lines */}
                                                                                        <div className={`absolute left-1 right-1 flex flex-col gap-[1px] items-center ${getPreviewBottomClass(lastUsedSettings.position)}`}>
                                                                                            <div className={`h-[2px] w-[75%] rounded-full ${getSubtitlePreviewBgClass(lastUsedSettings.color)}`} />
                                                                                            {lastUsedSettings.lines > 1 && (
                                                                                                <div className={`h-[2px] w-[55%] rounded-full ${getSubtitlePreviewBgClass(lastUsedSettings.color)}`} />
                                                                                            )}
                                                                                        </div>
                                                                                    </>
                                                                                ) : (
                                                                                    <div className="absolute inset-0 flex items-center justify-center">
                                                                                        <svg className="w-4 h-4 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                                                                        </svg>
                                                                                    </div>
                                                                                )}
                                                                                {/* Home indicator */}
                                                                                <div className="absolute bottom-1 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-slate-600 rounded-full" />
                                                                            </div>

                                                                            {/* Text content */}
                                                                            <div className="flex-1 min-w-0 relative">
                                                                                <div className="flex items-center gap-1.5 mb-0.5">
                                                                                    <span className="text-sm">🕐</span>
                                                                                    <span className="font-semibold text-xs truncate">{t('styleLastUsedName') || 'Last Used'}</span>
                                                                                </div>
                                                                                <p className="text-[10px] text-[var(--muted)] leading-tight line-clamp-2">
                                                                                    {lastUsedSettings ? (t('styleLastUsedDesc') || 'Your most recent settings') : (t('styleLastUsedNoHistory') || 'No previous exports yet')}
                                                                                </p>
                                                                            </div>

                                                                            {activePreset === 'lastUsed' && (
                                                                                <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-[var(--accent)] flex items-center justify-center animate-scale-in">
                                                                                    <svg className="w-2.5 h-2.5 text-[#031018]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                                                                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                                                                    </svg>
                                                                                </div>
                                                                            )}
                                                                        </button>
                                                                    </div>

                                                                    <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] mb-3">Custom Settings</h4>
                                                                    <SubtitlePositionSelector
                                                                        value={subtitlePosition}
                                                                        onChange={(v) => { setSubtitlePosition(v); setActivePreset(null); }}
                                                                        lines={maxSubtitleLines}
                                                                        onChangeLines={(v) => { setMaxSubtitleLines(v); setActivePreset(null); }}
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
                                                                        previewVideoUrl={previewVideoUrl || undefined}
                                                                        cues={cues}
                                                                        hidePreview={true}
                                                                    />
                                                                </div>
                                                            )}
                                                        </div>

                                                        <div className="pt-4 mt-4 border-t border-[var(--border)]/60 space-y-4">
                                                            <div className="flex flex-wrap gap-3">
                                                                {videoUrl && (
                                                                    <button
                                                                        className="btn-primary w-full items-center justify-center gap-2 inline-flex disabled:opacity-50 h-10 shadow-lg shadow-primary/20 hover:shadow-primary/40 transition-all font-semibold"
                                                                        onClick={() => {
                                                                            // Use detected dimensions or default to vertical HD
                                                                            const res = videoInfo ? `${videoInfo.width}x${videoInfo.height}` : '1080x1920';
                                                                            handleExport(res);
                                                                        }}
                                                                        disabled={exportingResolutions[videoInfo ? `${videoInfo.width}x${videoInfo.height}` : '1080x1920']}
                                                                    >
                                                                        {exportingResolutions[videoInfo ? `${videoInfo.width}x${videoInfo.height}` : '1080x1920'] ? (
                                                                            <><span className="animate-spin">⏳</span> {'Rendering...'}</>
                                                                        ) : (
                                                                            <>✨ {'Export Video'}</>
                                                                        )}
                                                                    </button>
                                                                )}
                                                            </div>

                                                            <ViralIntelligence jobId={selectedJob.id} />
                                                        </div>

                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                ) : null}

                            </>
                        )}
                        <VideoModal
                            isOpen={showPreview}
                            onClose={handleClosePreview}
                            videoUrl={videoUrl || ''}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
}

