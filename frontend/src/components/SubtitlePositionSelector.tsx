'use client';

import React, { useCallback, useEffect, useId, useRef, useState, memo } from 'react';
import Image from 'next/image';
import { useI18n } from '@/context/I18nContext';
import { InfoTooltip } from '@/components/InfoTooltip';
import { SubtitleOverlay, Cue } from './SubtitleOverlay';

// Constants moved outside component
const MORE_COLORS = [
    { value: '#FF0000', label: 'Red' },
    { value: '#FF7F00', label: 'Orange' },
    { value: '#FFFF00', label: 'Yellow' },
    { value: '#7FFF00', label: 'Chartreuse' },
    { value: '#00FF00', label: 'Green' },
    { value: '#00FF7F', label: 'Spring Green' },
    { value: '#00FFFF', label: 'Cyan' },
    { value: '#007FFF', label: 'Azure' },
    { value: '#0000FF', label: 'Blue' },
    { value: '#7F00FF', label: 'Violet' },
    { value: '#FF00FF', label: 'Magenta' },
    { value: '#FF007F', label: 'Rose' },
    { value: '#FFFFFF', label: 'White' },
    { value: '#C0C0C0', label: 'Silver' },
    { value: '#808080', label: 'Gray' },
    { value: '#000000', label: 'Black' }
];

const getPreviewBottom = (pos: number) => {
    return `${pos * 1.5 + 10}%`;
};

interface SubtitlePreviewProps {
    previewVideoUrl?: string;
    thumbnailUrl?: string | null;
    cues: Cue[];
    value: number; // position
    subtitleColor?: string;
    subtitleSize: number;
    lines: number;
    karaokeEnabled: boolean;
    shadowStrength: number;
    watermarkEnabled: boolean;
}

const SubtitlePreview = memo(({
    previewVideoUrl,
    thumbnailUrl,
    cues,
    value,
    subtitleColor,
    subtitleSize,
    lines,
    karaokeEnabled,
    shadowStrength,
    watermarkEnabled
}: SubtitlePreviewProps) => {
    const { t } = useI18n();
    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    const [isPlaying, setIsPlaying] = useState(true);
    const [currentTime, setCurrentTime] = useState(0);
    const [isMuted, setIsMuted] = useState(true);
    const [duration, setDuration] = useState(0);

    const togglePlay = useCallback((e?: React.SyntheticEvent) => {
        e?.stopPropagation();
        if (!videoRef.current) return;
        if (videoRef.current.paused) {
            videoRef.current.play().catch(e => console.error("Play failed", e));
            setIsPlaying(true);
        } else {
            videoRef.current.pause();
            setIsPlaying(false);
        }
    }, []);

    const toggleMute = useCallback((e: React.MouseEvent) => {
        e.stopPropagation();
        if (!videoRef.current) return;
        videoRef.current.muted = !videoRef.current.muted;
        setIsMuted(videoRef.current.muted);
    }, []);

    const handleSeek = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        e.stopPropagation();
        const time = Number(e.target.value);
        if (videoRef.current) {
            videoRef.current.currentTime = time;
            setCurrentTime(time);
        }
    }, []);

    const handleTimeUpdate = () => {
        if (videoRef.current) {
            setCurrentTime(videoRef.current.currentTime);
        }
    };

    const handleLoadedMetadata = () => {
        if (videoRef.current) {
            setDuration(videoRef.current.duration);
        }
    };

    return (
        <div className="flex-shrink-0 flex flex-col items-center pt-2">
            <div className="mb-4 text-center">
                <h4 className="text-sm font-semibold text-[var(--foreground)] uppercase tracking-wide mb-1">
                    {t('previewWindowLabel')}
                </h4>
                <p className="text-[10px] text-[var(--muted)] max-w-[160px] leading-tight">
                    {t('previewWindowDesc')}
                </p>
            </div>

            {/* Phone Mockup */}
            <div ref={containerRef} className="relative w-[180px] h-[320px] bg-slate-800 rounded-[30px] border-[6px] border-slate-700 overflow-hidden shadow-2xl ring-1 ring-white/10">
                {/* Phone UI Elements */}
                <div className="absolute top-3 left-1/2 -translate-x-1/2 w-16 h-4 bg-black/60 rounded-full blur-[0.5px] z-10" />
                <div className="absolute top-3.5 right-4 flex gap-1 z-10">
                    <div className="w-4 h-2.5 bg-white/40 rounded-[2px]" />
                    <div className="w-0.5 h-1.5 bg-white/40 rounded-[1px] self-center" />
                </div>
                <div className="absolute bottom-20 right-3 w-7 flex flex-col gap-4 items-center z-10 pointer-events-none">
                    <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                    <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                    <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                </div>
                <div className="absolute bottom-6 left-4 right-12 flex flex-col gap-2 z-10 pointer-events-none">
                    <div className="h-2.5 w-3/4 bg-white/30 rounded-full" />
                    <div className="h-2.5 w-1/2 bg-white/25 rounded-full" />
                </div>

                {/* Phone Content */}
                <div
                    className="absolute inset-0 bg-gray-900 cursor-pointer group"
                    onClick={togglePlay}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            togglePlay(e);
                        }
                    }}
                    role="button"
                    tabIndex={0}
                    aria-label={t('previewVideoToggle') || 'Preview video, tap to toggle play'}
                    aria-pressed={isPlaying}
                >
                    {previewVideoUrl && cues.length > 0 ? (
                        <>
                            <video
                                ref={videoRef}
                                src={previewVideoUrl}
                                className="absolute inset-0 w-full h-full object-cover"
                                loop
                                muted={isMuted}
                                playsInline
                                autoPlay
                                onTimeUpdate={handleTimeUpdate}
                                onLoadedMetadata={handleLoadedMetadata}
                                onPlay={() => setIsPlaying(true)}
                                onPause={() => setIsPlaying(false)}
                            />

                            <SubtitleOverlay
                                currentTime={currentTime}
                                cues={cues}
                                settings={{
                                    position: value,
                                    color: subtitleColor || '#FFFF00',
                                    fontSize: subtitleSize,
                                    karaoke: karaokeEnabled,
                                    maxLines: lines,
                                    shadowStrength: shadowStrength
                                }}
                                videoWidth={180}
                            />

                            {watermarkEnabled && (
                                <div
                                    className="absolute bottom-6 right-4 z-20 animate-in fade-in duration-300 pointer-events-none"
                                    style={{ width: '25%' }}
                                >
                                    <Image
                                        src="/ascentia-logo.png"
                                        alt="Watermark"
                                        width={0}
                                        height={0}
                                        sizes="20vw"
                                        className="w-full h-auto opacity-90"
                                    />
                                </div>
                            )}

                            {!isPlaying && (
                                <div className="absolute inset-0 flex items-center justify-center bg-black/30 animate-in fade-in z-30">
                                    <div className="w-12 h-12 bg-white/20 backdrop-blur-sm rounded-full flex items-center justify-center shadow-lg">
                                        <svg className="w-6 h-6 text-white ml-1" viewBox="0 0 24 24" fill="currentColor">
                                            <path d="M8 5v14l11-7z" />
                                        </svg>
                                    </div>
                                </div>
                            )}

                            <div
                                onClick={(e) => e.stopPropagation()}
                                className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-black/80 to-transparent z-40 flex flex-col justify-end pb-3 px-3 transition-opacity duration-200 opacity-0 group-hover:opacity-100"
                            >
                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={togglePlay}
                                        className="w-5 h-5 flex items-center justify-center text-white hover:text-[var(--accent)] transition-colors"
                                        aria-label={isPlaying ? (t('pausePreview') || 'Pause preview') : (t('playPreview') || 'Play preview')}
                                        title={isPlaying ? (t('pausePreview') || 'Pause preview') : (t('playPreview') || 'Play preview')}
                                        aria-pressed={isPlaying}
                                    >
                                        {isPlaying ? (
                                            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" /></svg>
                                        ) : (
                                            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                                        )}
                                    </button>

                                    <div className="flex-1 h-8 flex items-center relative group/scrubber">
                                        <input
                                            aria-label={t('seekVideo') || 'Seek video'}
                                            type="range"
                                            min={0}
                                            max={duration || 100}
                                            value={currentTime}
                                            onChange={handleSeek}
                                            className="w-full h-1 bg-white/30 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--accent)] [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:hover:scale-125"
                                        />
                                    </div>

                                    <button
                                        onClick={toggleMute}
                                        className="w-5 h-5 flex items-center justify-center text-white hover:text-[var(--accent)] transition-colors"
                                        aria-label={isMuted ? (t('unmutePreview') || 'Unmute preview') : (t('mutePreview') || 'Mute preview')}
                                        title={isMuted ? (t('unmutePreview') || 'Unmute preview') : (t('mutePreview') || 'Mute preview')}
                                        aria-pressed={isMuted}
                                    >
                                        {isMuted ? (
                                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" shapeRendering="geometricPrecision" />
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
                                            </svg>
                                        ) : (
                                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                                            </svg>
                                        )}
                                    </button>
                                </div>
                            </div>
                        </>
                    ) : (
                        <>
                            {thumbnailUrl ? (
                                <Image
                                    src={thumbnailUrl}
                                    alt="Video preview"
                                    fill
                                    unoptimized
                                    sizes="(max-width: 768px) 100vw, 33vw"
                                    className="absolute inset-0 object-cover opacity-80"
                                />
                            ) : (
                                <div className="absolute inset-0 bg-gradient-to-br from-purple-500/20 via-blue-500/20 to-purple-500/20" />
                            )}

                            <div
                                className="absolute left-3 right-3 flex flex-col gap-0.5 items-center transition-all duration-300 ease-out z-20 pointer-events-none"
                                style={{
                                    bottom: getPreviewBottom(value),
                                }}
                            >
                                <h3
                                    className="text-center font-black uppercase leading-[1.1] transition-all duration-300"
                                    style={{
                                        color: subtitleColor || '#FFFF00',
                                        fontSize: `${(subtitleSize / 100) * 1.5}rem`,
                                        textShadow: '2px 2px 0px rgba(0,0,0,0.8), -1px -1px 0 rgba(0,0,0,0.8), 1px -1px 0 rgba(0,0,0,0.8), -1px 1px 0 rgba(0,0,0,0.8)'
                                    }}
                                >
                                    {lines === 0 ? "WATCH" : "THIS IS HOW"}
                                </h3>
                                {lines > 0 && (
                                    <h3
                                        className="text-center font-black uppercase leading-[1.1] transition-all duration-300"
                                        style={{
                                            color: subtitleColor || '#FFFF00',
                                            fontSize: `${(subtitleSize / 100) * 1.5}rem`,
                                            textShadow: '2px 2px 0px rgba(0,0,0,0.8), -1px -1px 0 rgba(0,0,0,0.8), 1px -1px 0 rgba(0,0,0,0.8), -1px 1px 0 rgba(0,0,0,0.8)'
                                        }}
                                    >
                                        {lines >= 2 ? "YOUR SUBTITLES LOOK" : "..."}
                                    </h3>
                                )}
                                {lines > 1 && (
                                    <h3
                                        className="text-center font-black uppercase leading-[1.1] transition-all duration-300"
                                        style={{
                                            color: subtitleColor || '#FFFF00',
                                            fontSize: `${(subtitleSize / 100) * 1.5}rem`,
                                            textShadow: '2px 2px 0px rgba(0,0,0,0.8), -1px -1px 0 rgba(0,0,0,0.8), 1px -1px 0 rgba(0,0,0,0.8), -1px 1px 0 rgba(0,0,0,0.8)'
                                        }}
                                    >
                                        ON SCREEN
                                    </h3>
                                )}
                            </div>

                            {(previewVideoUrl && cues.length === 0) && (
                                <div className="absolute top-8 left-2 right-2 bg-black/60 backdrop-blur-md border border-white/10 rounded px-2 py-1 z-20">
                                    <p className="text-[9px] text-white/90 text-center font-medium leading-tight">
                                        Subtitles pending...
                                    </p>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
});
SubtitlePreview.displayName = 'SubtitlePreview';

export interface SubtitlePositionSelectorProps {
    value: number;  // 5-35 (percentage from bottom)
    onChange: (value: number) => void;
    lines: number;
    onChangeLines: (lines: number) => void;
    thumbnailUrl?: string | null;
    disableMaxLines?: boolean;
    subtitleSize?: number;  // 50-150 scale (percentage)
    onChangeSize?: (size: number) => void;
    karaokeEnabled?: boolean;
    onChangeKaraoke?: (enabled: boolean) => void;
    karaokeSupported?: boolean;
    subtitleColor?: string;
    onChangeColor?: (color: string) => void;
    colors?: Array<{ label: string; value: string; ass: string }>;
    shadowStrength?: number;
    previewVideoUrl?: string;
    cues?: Cue[];
    hidePreview?: boolean;
    watermarkEnabled?: boolean;
    onChangeWatermark?: (enabled: boolean) => void;
}

export const SubtitlePositionSelector = React.memo<SubtitlePositionSelectorProps>(({
    value,
    onChange,
    lines,
    onChangeLines,
    thumbnailUrl,
    subtitleColor,
    onChangeColor,
    colors = [],
    disableMaxLines,
    subtitleSize = 100,  // Default 100%
    onChangeSize,
    karaokeEnabled = true,
    onChangeKaraoke,
    karaokeSupported = false,
    shadowStrength = 4,
    previewVideoUrl,
    cues = [],
    hidePreview,
    watermarkEnabled = false,
    onChangeWatermark,
}) => {
    const { t } = useI18n();
    const colorLabelId = useId();
    const sizeLabelId = useId();
    const positionLabelId = useId();
    const karaokeLabelId = useId();
    const watermarkLabelId = useId();
    const linesLabelId = useId();

    const [showColorGrid, setShowColorGrid] = useState(false);
    const gridRef = useRef<HTMLDivElement>(null);

    // Close color grid when clicking outside
    useEffect(() => {
        function handleClickOutside(event: MouseEvent) {
            if (gridRef.current && !gridRef.current.contains(event.target as Node)) {
                setShowColorGrid(false);
            }
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
        };
    }, []);

    // Preset tick marks for position
    const positionPresets = [
        { value: 10, label: t('positionLow') },
        { value: 20, label: t('positionMiddle') },
        { value: 30, label: t('positionHigh') },
    ];

    // Preset tick marks for size
    const sizePresets = [
        { value: 70, label: t('sizeSmall') },
        { value: 85, label: t('sizeMedium') },
        { value: 100, label: t('sizeBig') },
        { value: 150, label: t('sizeExtraBig') },
    ];

    const handleLineChange = useCallback((num: number) => (e: React.MouseEvent) => {
        e.stopPropagation();
        onChangeLines(num);
    }, [onChangeLines]);

    const lineOptions = [
        { value: 0, label: t('lines1Word'), desc: t('lines1WordDesc') },
        { value: 1, label: t('linesSingle'), desc: t('linesSingleDesc') },
        { value: 2, label: t('linesDouble'), desc: t('linesDoubleDesc') },
        { value: 3, label: t('linesThree'), desc: t('linesThreeDesc') },
    ];

    return (
        <div className="space-y-6">
            <div className="flex flex-col xl:flex-row gap-8">
                {/* Controls Area */}
                <div className="flex-1 space-y-6">
                    {/* Top Row: Size & Lines */}
                    <div className="flex flex-col sm:flex-row gap-4">
                        {/* Size Slider */}
                        {onChangeSize && (
                            <div className="flex-1 min-w-[200px]">
                                <div className="flex items-center gap-2 mb-3">
                                    <label htmlFor={sizeLabelId} className="block text-sm font-medium text-[var(--muted)]">
                                        {t('sizeLabel')}
                                    </label>
                                    <InfoTooltip ariaLabel={`${t('infoPrefix')} ${t('sizeLabel')}`}>
                                        <div className="space-y-2">
                                            <div className="font-semibold text-[11px]">{t('sizeLabel')}</div>
                                            <p className="text-[var(--muted)] leading-snug">{t('tooltipSizeDesc')}</p>
                                            <div className="flex items-end justify-between gap-3 rounded-lg border border-white/10 bg-black/20 p-2">
                                                <span aria-hidden="true" className="text-[10px] font-bold text-white/70">
                                                    Aa
                                                </span>
                                                <span aria-hidden="true" className="text-base font-black text-white">
                                                    Aa
                                                </span>
                                            </div>
                                        </div>
                                    </InfoTooltip>
                                </div>
                                <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)]">
                                    {/* Size Preview Text */}
                                    <div className="flex items-center justify-center mb-4">
                                        <span
                                            className="font-bold text-[var(--foreground)]"
                                            style={{ fontSize: '24px' }}
                                            aria-hidden="true"
                                        >
                                            Aa
                                        </span>
                                    </div>

                                    {/* Slider */}
                                    <div className="relative">
                                        <input
                                            id={sizeLabelId}
                                            type="range"
                                            min={50}
                                            max={150}
                                            value={subtitleSize}
                                            onChange={(e) => {
                                                e.stopPropagation();
                                                onChangeSize(Number(e.target.value));
                                            }}
                                            onClick={(e) => e.stopPropagation()}
                                            className="w-full h-2 rounded-full appearance-none cursor-pointer bg-[var(--border)]
                                                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]
                                                [&::-webkit-slider-thumb]:appearance-none
                                                [&::-webkit-slider-thumb]:w-5
                                                [&::-webkit-slider-thumb]:h-5
                                                [&::-webkit-slider-thumb]:rounded-full
                                                [&::-webkit-slider-thumb]:bg-[var(--accent)]
                                                [&::-webkit-slider-thumb]:shadow-lg
                                                [&::-webkit-slider-thumb]:cursor-pointer
                                                [&::-webkit-slider-thumb]:transition-transform
                                                [&::-webkit-slider-thumb]:hover:scale-110
                                                [&::-moz-range-thumb]:w-5
                                                [&::-moz-range-thumb]:h-5
                                                [&::-moz-range-thumb]:rounded-full
                                                [&::-moz-range-thumb]:bg-[var(--accent)]
                                                [&::-moz-range-thumb]:border-0
                                                [&::-moz-range-thumb]:shadow-lg
                                                [&::-moz-range-thumb]:cursor-pointer"
                                            style={{
                                                background: `linear-gradient(to right, var(--accent) 0%, var(--accent) ${((subtitleSize - 50) / 100) * 100}%, var(--border) ${((subtitleSize - 50) / 100) * 100}%, var(--border) 100%)`
                                            }}
                                        />

                                        {/* Preset Tick Marks */}
                                        <div className="flex justify-between mt-2 px-1">
                                            {sizePresets.map((preset) => (
                                                <button
                                                    key={preset.value}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        onChangeSize(preset.value);
                                                    }}
                                                    className={`text-[10px] px-1.5 py-0.5 rounded transition-all ${subtitleSize === preset.value
                                                        ? 'text-[var(--accent)] font-medium'
                                                        : 'text-[var(--muted)] hover:text-[var(--foreground)]'
                                                        }`}
                                                >
                                                    {preset.label}
                                                </button>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Position Slider - Under Size */}
                                    <div className="mt-4 pt-4 border-t border-[var(--border)]">
                                        <div className="flex items-center gap-2 mb-3">
                                            <label htmlFor={positionLabelId} className="text-xs font-medium text-[var(--muted)]">
                                                {t('positionLabel')}
                                            </label>
                                            <InfoTooltip ariaLabel={`${t('infoPrefix')} ${t('positionLabel')}`}>
                                                <div className="space-y-2">
                                                    <div className="font-semibold text-[11px]">{t('positionLabel')}</div>
                                                    <p className="text-[var(--muted)] leading-snug">{t('tooltipPositionDesc')}</p>
                                                    <div className="grid grid-cols-3 gap-2 rounded-lg border border-white/10 bg-black/20 p-2">
                                                        <div className="relative h-12 rounded-md border border-white/10 bg-white/5">
                                                            <div className="absolute left-1 right-1 top-2 h-1 rounded-full bg-white/20" />
                                                        </div>
                                                        <div className="relative h-12 rounded-md border border-white/10 bg-white/5">
                                                            <div className="absolute left-1 right-1 top-1/2 -translate-y-1/2 h-1 rounded-full bg-white/20" />
                                                        </div>
                                                        <div className="relative h-12 rounded-md border border-white/10 bg-white/5">
                                                            <div className="absolute left-1 right-1 bottom-2 h-1 rounded-full bg-white/20" />
                                                        </div>
                                                    </div>
                                                </div>
                                            </InfoTooltip>
                                        </div>
                                        {/* Centered Mini phone preview - like the Aa preview above */}
                                        <div className="flex items-center justify-center mb-4">
                                            <div className="relative w-8 h-14 bg-slate-700/50 rounded-lg border border-slate-600/50 overflow-hidden">
                                                {/* Subtitle line indicator */}
                                                <div
                                                    className="absolute left-1 right-1 h-1 bg-[var(--accent)] rounded-full transition-all duration-200 shadow-[0_0_6px_var(--accent)]"
                                                    style={{ bottom: `${20 + ((value - 5) / 30) * 65}%` }}
                                                />
                                            </div>
                                        </div>

                                        {/* Slider */}
                                        <div className="relative">
                                            <input
                                                id={positionLabelId}
                                                type="range"
                                                min={5}
                                                max={35}
                                                value={value}
                                                onChange={(e) => {
                                                    e.stopPropagation();
                                                    onChange(Number(e.target.value));
                                                }}
                                                onClick={(e) => e.stopPropagation()}
                                                className="w-full h-2 rounded-full appearance-none cursor-pointer bg-[var(--border)]
                                                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]
                                                    [&::-webkit-slider-thumb]:appearance-none
                                                    [&::-webkit-slider-thumb]:w-5
                                                    [&::-webkit-slider-thumb]:h-5
                                                    [&::-webkit-slider-thumb]:rounded-full
                                                    [&::-webkit-slider-thumb]:bg-[var(--accent)]
                                                    [&::-webkit-slider-thumb]:shadow-lg
                                                    [&::-webkit-slider-thumb]:cursor-pointer
                                                    [&::-webkit-slider-thumb]:transition-transform
                                                    [&::-webkit-slider-thumb]:hover:scale-110
                                                    [&::-moz-range-thumb]:w-5
                                                    [&::-moz-range-thumb]:h-5
                                                    [&::-moz-range-thumb]:rounded-full
                                                    [&::-moz-range-thumb]:bg-[var(--accent)]
                                                    [&::-moz-range-thumb]:border-0
                                                    [&::-moz-range-thumb]:shadow-lg
                                                    [&::-moz-range-thumb]:cursor-pointer"
                                                style={{
                                                    background: `linear-gradient(to right, var(--accent) 0%, var(--accent) ${((value - 5) / 30) * 100}%, var(--border) ${((value - 5) / 30) * 100}%, var(--border) 100%)`
                                                }}
                                            />
                                            {/* Preset Tick Marks */}
                                            <div className="flex justify-between mt-2 px-1">
                                                {positionPresets.map((preset) => (
                                                    <button
                                                        key={preset.value}
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            onChange(preset.value);
                                                        }}
                                                        className={`text-[10px] px-1.5 py-0.5 rounded transition-all ${value === preset.value
                                                            ? 'text-[var(--accent)] font-medium'
                                                            : 'text-[var(--muted)] hover:text-[var(--foreground)]'
                                                            }`}
                                                    >
                                                        {preset.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Lines Selector */}
                        <div className="flex-1 min-w-[200px]">
                            <div className="flex items-center gap-2 mb-3">
                                <label id={linesLabelId} className="block text-sm font-medium text-[var(--muted)]">
                                    {t('maxLinesLabel')}
                                </label>
                                <InfoTooltip ariaLabel={`${t('infoPrefix')} ${t('maxLinesLabel')}`}>
                                    <div className="space-y-2">
                                        <div className="font-semibold text-[11px]">{t('maxLinesLabel')}</div>
                                        <p className="text-[var(--muted)] leading-snug">{t('tooltipMaxLinesDesc')}</p>
                                        <div className="rounded-lg border border-white/10 bg-black/20 p-2">
                                            <div className="space-y-1">
                                                <div className="h-1.5 w-full rounded-full bg-[var(--accent)]/50" />
                                                <div className="h-1.5 w-4/5 rounded-full bg-[var(--accent)]/35" />
                                                <div className="h-1.5 w-3/5 rounded-full bg-white/10" />
                                            </div>
                                        </div>
                                    </div>
                                </InfoTooltip>
                            </div>
                            {disableMaxLines ? (
                                /* Disabled state for Standard model */
                                <div className="p-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface)]/50 h-full">
                                    <div className="flex items-center gap-2 mb-2">
                                        <span className="text-lg">🎯</span>
                                        <span className="font-medium text-sm text-[var(--muted)]">{t('linesAuto')}</span>
                                    </div>
                                    <p className="text-xs text-[var(--muted)]/70">
                                        {t('linesAutoDesc')}
                                    </p>
                                </div>
                            ) : (
                                <div className="flex flex-col gap-2" role="radiogroup" aria-labelledby={linesLabelId}>
                                    {lineOptions.map((opt) => (
                                        <button
                                            key={opt.value}
                                            role="radio"
                                            aria-checked={lines === opt.value}
                                            onClick={handleLineChange(opt.value)}
                                            className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)] ${lines === opt.value
                                                ? 'border-[var(--accent)] bg-[var(--accent)]/5 ring-1 ring-[var(--accent)] shadow-[0_0_15px_rgba(var(--accent-rgb),0.1)]'
                                                : 'border-[var(--border)] hover:border-[var(--accent)]/40 hover:bg-[var(--surface-elevated)]'
                                                }`}
                                        >
                                            <div>
                                                <div className={`font-medium text-sm transition-colors ${lines === opt.value ? 'text-[var(--accent)]' : ''}`}>{opt.label}</div>
                                                <div className="text-xs text-[var(--muted)]/80">{opt.desc}</div>
                                            </div>
                                            {lines === opt.value && (
                                                <div className="w-2 h-2 rounded-full bg-[var(--accent)] shadow-sm animate-scale-in" />
                                            )}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Middle Row: Colors */}
                    {colors && onChangeColor && (
                        <div className="w-full">
                            <div className="flex items-center gap-2 mb-3">
                                <label id={colorLabelId} className="block text-sm font-medium text-[var(--muted)]">
                                    {t('colorLabel')}
                                </label>
                                <InfoTooltip ariaLabel={`${t('infoPrefix')} ${t('colorLabel')}`}>
                                    <div className="space-y-2">
                                        <div className="font-semibold text-[11px]">{t('colorLabel')}</div>
                                        <p className="text-[var(--muted)] leading-snug">{t('tooltipColorDesc')}</p>
                                        <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/20 p-2">
                                            <span aria-hidden="true" className="h-3.5 w-3.5 rounded-full bg-[#FFFF00] border border-white/10" />
                                            <span aria-hidden="true" className="h-3.5 w-3.5 rounded-full bg-white border border-white/10" />
                                            <span aria-hidden="true" className="h-3.5 w-3.5 rounded-full bg-[#00FFFF] border border-white/10" />
                                        </div>
                                    </div>
                                </InfoTooltip>
                            </div>
                            <div
                                className="flex items-center gap-3 p-4 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] min-h-[88px]"
                                role="radiogroup"
                                aria-labelledby={colorLabelId}
                            >
                                {/* Color Swatches */}
                                <div className="flex flex-nowrap gap-4 justify-center w-full items-center relative" ref={gridRef}>
                                    {/* First 3 Presets */}
                                    {colors.slice(0, 3).map((c) => (
                                        <button
                                            key={c.value}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onChangeColor(c.value);
                                                setShowColorGrid(false);
                                            }}
                                            className="group relative p-1 transition-transform active:scale-95 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]"
                                            title={c.label}
                                            role="radio"
                                            aria-checked={subtitleColor === c.value}
                                            aria-label={c.label}
                                        >
                                            <div
                                                className={`w-10 h-10 rounded-full border-2 shadow-sm transition-all duration-300 ease-out ${subtitleColor === c.value
                                                    ? 'border-white scale-110 ring-2 ring-white/20'
                                                    : 'border-transparent hover:scale-110 hover:border-white/30 opacity-80 hover:opacity-100'
                                                    }`}
                                                style={{ backgroundColor: c.value }}
                                            />
                                        </button>
                                    ))}

                                    {/* More Colors Button (Toggle Popover) */}
                                    <div className="relative">
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setShowColorGrid(!showColorGrid);
                                            }}
                                            className="group relative p-1 transition-transform active:scale-95 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]"
                                            title={t('moreColors') || "More Colors"}
                                            aria-expanded={showColorGrid}
                                            aria-haspopup="true"
                                        >
                                            <div
                                                className={`w-10 h-10 rounded-full border-2 shadow-md transition-all duration-300 ease-out flex items-center justify-center overflow-hidden bg-[var(--surface)] ${showColorGrid || !colors.slice(0, 3).some(c => c.value === subtitleColor)
                                                    ? 'border-white ring-2 ring-white/20'
                                                    : 'border-[var(--border)] hover:scale-110 hover:border-white/30'
                                                    }`}
                                            >
                                                {/* Conic Gradient Icon */}
                                                <div
                                                    className="w-full h-full opacity-80 group-hover:opacity-100 transition-opacity"
                                                    style={{
                                                        background: 'conic-gradient(from 180deg at 50% 50%, #FF0000 0deg, #00FF00 120deg, #0000FF 240deg, #FF0000 360deg)'
                                                    }}
                                                />

                                                {/* Plus Icon Overlay */}
                                                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                                                    <svg className="w-5 h-5 text-white drop-shadow-md" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                                                    </svg>
                                                </div>
                                            </div>
                                        </button>

                                        {/* Color Grid Popover */}
                                        {showColorGrid && (
                                            <div
                                                className="absolute top-full left-1/2 -translate-x-1/2 mt-3 p-3 bg-[var(--surface-elevated)] border border-[var(--border)] rounded-xl shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-200 min-w-[180px]"
                                                role="radiogroup"
                                                aria-label={t('moreColors') || 'More Colors'}
                                            >
                                                <div className="grid grid-cols-4 gap-2">
                                                    {MORE_COLORS.map((color) => (
                                                        <button
                                                            key={color.value}
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                onChangeColor(color.value);
                                                                setShowColorGrid(false);
                                                            }}
                                                            className="w-8 h-8 rounded-full border border-white/10 hover:border-white hover:scale-110 transition-all shadow-sm relative focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:outline-none"
                                                            style={{ backgroundColor: color.value }}
                                                            title={color.label}
                                                            aria-label={color.label}
                                                            role="radio"
                                                            aria-checked={subtitleColor === color.value}
                                                        >
                                                            {subtitleColor === color.value && (
                                                                <div className="absolute inset-0 flex items-center justify-center">
                                                                    <div className="w-2 h-2 bg-black/40 rounded-full ring-1 ring-white/50" />
                                                                </div>
                                                            )}
                                                        </button>
                                                    ))}
                                                </div>
                                                {/* Triangle Pointer */}
                                                <div className="absolute -top-1.5 left-1/2 -translate-x-1/2 w-3 h-3 bg-[var(--surface-elevated)] border-t border-l border-[var(--border)] rotate-45" />
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Bottom Row: Toggles (Karaoke & Watermark) */}
                    <div className="flex flex-col sm:flex-row gap-4">
                        {/* Karaoke Toggle */}
                        {onChangeKaraoke && karaokeSupported && (
                            <div className="flex-1 min-w-[200px]">
                                <div className="flex items-center gap-2 mb-3">
                                    <label id={karaokeLabelId} className="block text-sm font-medium text-[var(--muted)]">
                                        {t('karaokeLabel') || 'Karaoke'}
                                    </label>
                                    <InfoTooltip ariaLabel={`${t('infoPrefix')} ${t('karaokeLabel') || 'Karaoke'}`}>
                                        <div className="space-y-2">
                                            <div className="font-semibold text-[11px]">{t('karaokeMode')}</div>
                                            <p className="text-[var(--muted)] leading-snug">{t('tooltipKaraokeDesc')}</p>
                                            <div className="rounded-lg border border-white/10 bg-black/20 p-2">
                                                <div className="flex items-center justify-between text-[9px] font-semibold text-white/60 uppercase tracking-wide">
                                                    <span>{t('karaokeStatic')}</span>
                                                    <span className="text-white/40">→</span>
                                                    <span className="text-orange-300">{t('karaokeActive')}</span>
                                                </div>
                                                <div className="mt-2 rounded-md bg-white/5 px-2 py-1 text-[10px] font-black uppercase tracking-wide">
                                                    <span className="rounded bg-orange-500 px-1 text-white">HELLO</span>{' '}
                                                    <span className="text-white/50">WORLD</span>
                                                </div>
                                                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                                                    <div className="h-full w-1/2 rounded-full bg-orange-500" />
                                                </div>
                                            </div>
                                        </div>
                                    </InfoTooltip>
                                </div>
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onChangeKaraoke(!karaokeEnabled);
                                    }}
                                    role="switch"
                                    aria-checked={karaokeEnabled}
                                    aria-labelledby={karaokeLabelId}
                                    className={`w-full p-4 rounded-xl border text-left transition-all duration-300 flex items-center justify-between group min-h-[88px] relative overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)] ${karaokeEnabled
                                        ? 'border-orange-500/50 bg-gradient-to-r from-orange-500/10 to-transparent shadow-[0_0_20px_rgba(249,115,22,0.1)]'
                                        : 'border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--surface-elevated)]'
                                        }`}
                                >
                                    {/* Active Indicator Line */}
                                    {karaokeEnabled && (
                                        <div className="absolute left-0 top-0 bottom-0 w-1 bg-orange-500 shadow-[0_0_10px_rgba(249,115,22,0.5)]" />
                                    )}

                                    <div className="flex flex-col gap-1 pl-2">
                                        <div className={`font-semibold text-base transition-colors ${karaokeEnabled ? 'text-orange-500' : 'text-[var(--foreground)]'}`}>
                                            {t('karaokeMode')}
                                        </div>
                                        <div className={`text-xs ${karaokeEnabled ? 'text-[var(--muted)]' : 'text-[var(--muted)]/70'}`}>
                                            {karaokeEnabled ? (t('activeWordsHighlighted') || 'Active words highlighted') : (t('standardCaptions') || 'Standard captions')}
                                        </div>
                                    </div>

                                    {/* Animated Icon */}
                                    <div className={`w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 ${karaokeEnabled ? 'bg-orange-500 text-white rotate-6 scale-110 shadow-lg shadow-orange-500/30' : 'bg-[var(--surface-elevated)] text-[var(--muted)] group-hover:scale-105'}`}>
                                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                                        </svg>
                                    </div>
                                </button>
                            </div>
                        )}

                        {/* Watermark Toggle - Nano Banana Sleek */}
                        {onChangeWatermark && (
                            <div className="flex-1 min-w-[200px]">
                                <div className="flex items-center gap-2 mb-3">
                                    <label id={watermarkLabelId} className="block text-sm font-medium text-[var(--muted)]">
                                        {t('watermarkLabel')}
                                    </label>
                                    <InfoTooltip ariaLabel={t('watermarkLabel')}>
                                        <div className="space-y-2">
                                            <div className="font-semibold text-[11px]">{t('watermarkBrand')}</div>
                                            <p className="text-[var(--muted)] leading-snug">{t('watermarkDesc')}</p>
                                        </div>
                                    </InfoTooltip>
                                </div>
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onChangeWatermark(!watermarkEnabled);
                                    }}
                                    role="switch"
                                    aria-checked={watermarkEnabled}
                                    aria-labelledby={watermarkLabelId}
                                    className={`w-full h-[88px] rounded-xl border text-left transition-all duration-300 flex items-center justify-between px-6 group relative overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)] ${watermarkEnabled
                                        ? 'border-[var(--accent)]/30 bg-[var(--accent)]/[0.03]'
                                        : 'border-[var(--border)] hover:border-[var(--foreground)]/20 hover:bg-white/[0.02]'
                                        }`}
                                >
                                    {/* Content */}
                                    <div className="flex flex-col gap-0.5 z-10">
                                        <div className={`font-semibold text-base tracking-tight transition-colors ${watermarkEnabled ? 'text-[var(--foreground)]' : 'text-[var(--foreground)]/80'}`}>
                                            {t('watermarkAffiliate')}
                                        </div>
                                        <div className="flex items-center gap-1.5">
                                            <span className={`text-[10px] uppercase tracking-wider font-mono ${watermarkEnabled ? 'text-[var(--accent)]' : 'text-[var(--muted)]'}`}>
                                                {watermarkEnabled ? t('statusActive') : t('statusDisabled')}
                                            </span>
                                            {watermarkEnabled && (
                                                <span className="w-1 h-1 rounded-full bg-[var(--accent)] shadow-[0_0_5px_var(--accent)]" />
                                            )}
                                        </div>
                                    </div>

                                    {/* Sleek Toggle Switch */}
                                    <div className="relative w-12 h-6 rounded-full bg-black/40 border border-white/10 shadow-inner overflow-hidden">
                                        {/* Track Fill */}
                                        <div
                                            className={`absolute inset-0 bg-[var(--accent)]/20 transition-transform duration-300 origin-left ${watermarkEnabled ? 'scale-x-100' : 'scale-x-0'}`}
                                        />

                                        {/* Thumb */}
                                        <div
                                            className={`absolute top-[2px] w-5 h-5 rounded-full shadow-md border transition-all duration-300 ease-out flex items-center justify-center ${watermarkEnabled
                                                ? 'left-[calc(100%-22px)] bg-[var(--accent)] border-[var(--accent)] shadow-[0_0_10px_rgba(var(--accent-rgb),0.3)]'
                                                : 'left-[2px] bg-[#222] border-white/10'}`}
                                        >
                                            {watermarkEnabled && (
                                                <div className="w-1.5 h-1.5 rounded-full bg-[#031018]" />
                                            )}
                                        </div>
                                    </div>

                                    {/* Subtle Ambient Glow when active */}
                                    {watermarkEnabled && (
                                        <div className="absolute top-1/2 right-6 -translate-y-1/2 w-20 h-20 bg-[var(--accent)]/10 blur-2xl -z-0 pointer-events-none" />
                                    )}
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                {/* Visual Preview - Phone Mockup */}
                {!hidePreview && (
                    <SubtitlePreview
                        previewVideoUrl={previewVideoUrl}
                        thumbnailUrl={thumbnailUrl}
                        cues={cues}
                        value={value}
                        subtitleColor={subtitleColor}
                        subtitleSize={subtitleSize}
                        lines={lines}
                        karaokeEnabled={karaokeEnabled}
                        shadowStrength={shadowStrength}
                        watermarkEnabled={watermarkEnabled}
                    />
                )}
            </div>
        </div>
    );
});

SubtitlePositionSelector.displayName = 'SubtitlePositionSelector';
