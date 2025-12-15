import React, { useCallback, useId, useRef, useState } from 'react';
import { useI18n } from '@/context/I18nContext';
import { SubtitleOverlay, Cue } from './SubtitleOverlay';

export interface SubtitlePositionSelectorProps {
    value: number;  // 5-35 (percentage from bottom)
    onChange: (value: number) => void;
    lines: number;
    onChangeLines: (lines: number) => void;
    thumbnailUrl?: string | null;
    // previewColor?: string; // Removed
    disableMaxLines?: boolean;
    subtitleSize?: number;  // 50-150 scale (percentage)
    onChangeSize?: (size: number) => void;
    karaokeEnabled?: boolean;
    onChangeKaraoke?: (enabled: boolean) => void;
    karaokeSupported?: boolean;
    subtitleColor?: string;
    onChangeColor?: (color: string) => void;
    colors?: Array<{ label: string; value: string; ass: string }>;
    shadowStrength?: number; // New
    previewVideoUrl?: string; // New: Live video blob
    cues?: Cue[]; // New: Transcription data
    hidePreview?: boolean; // New: Option to hide the phone mockup
}

export const SubtitlePositionSelector: React.FC<SubtitlePositionSelectorProps> = ({
    value,
    onChange,
    lines,
    onChangeLines,
    thumbnailUrl,
    // previewColor, // Removed
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
}) => {
    const { t } = useI18n();
    const colorLabelId = useId();
    const sizeLabelId = useId();
    const karaokeLabelId = useId();
    const linesLabelId = useId();

    const containerRef = useRef<HTMLDivElement>(null);
    const [isPlaying, setIsPlaying] = useState(true); // Auto-play by default
    const [currentTime, setCurrentTime] = useState(0);
    const videoRef = useRef<HTMLVideoElement>(null);
    const [isMuted, setIsMuted] = useState(true); // Default muted for autoplay
    const [duration, setDuration] = useState(0);

    // Sync play/pause
    const togglePlay = useCallback((e?: React.MouseEvent) => {
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

    // Update time for overlay
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

    // Map numeric position (5-35) to CSS 'bottom' percentage for preview
    const getPreviewBottom = (pos: number) => {
        return `${pos}%`;
    };



    // Preset tick marks for position
    const positionPresets = [
        { value: 6, label: t('positionLow') },
        { value: 16, label: t('positionMiddle') },
        { value: 45, label: t('positionHigh') },
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
                                <label htmlFor={sizeLabelId} className="block text-sm font-medium text-[var(--muted)] mb-3">
                                    {t('sizeLabel')}
                                </label>
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
                                        {/* Centered Mini phone preview - like the Aa preview above */}
                                        <div className="flex items-center justify-center mb-4">
                                            <div className="relative w-8 h-14 bg-slate-700/50 rounded-lg border border-slate-600/50 overflow-hidden">
                                                {/* Subtitle line indicator */}
                                                <div
                                                    className="absolute left-1 right-1 h-1 bg-[var(--accent)] rounded-full transition-all duration-200 shadow-[0_0_6px_var(--accent)]"
                                                    style={{ bottom: `${((value - 5) / 45) * 70 + 10}%` }}
                                                />
                                            </div>
                                        </div>

                                        {/* Slider */}
                                        <div className="relative">
                                            <input
                                                aria-label={t('positionLabel') || 'Subtitle Position'}
                                                type="range"
                                                min={5}
                                                max={50}
                                                value={value}
                                                onChange={(e) => {
                                                    e.stopPropagation();
                                                    onChange(Number(e.target.value));
                                                }}
                                                onClick={(e) => e.stopPropagation()}
                                                className="w-full h-2 rounded-full appearance-none cursor-pointer bg-[var(--border)]
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
                                                    background: `linear-gradient(to right, var(--accent) 0%, var(--accent) ${((value - 5) / 45) * 100}%, var(--border) ${((value - 5) / 45) * 100}%, var(--border) 100%)`
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
                            <label id={linesLabelId} className="block text-sm font-medium text-[var(--muted)] mb-3">
                                {t('maxLinesLabel')}
                            </label>
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
                                            className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between group ${lines === opt.value
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

                    {/* Bottom Row: Style & Karaoke */}
                    <div className="flex flex-col sm:flex-row gap-4">

                        {colors && onChangeColor && (
                            <div className="flex-1">
                                <label id={colorLabelId} className="block text-sm font-medium text-[var(--muted)] mb-3">
                                    {t('colorLabel')}
                                </label>
                                <div
                                    className="flex items-center gap-3 p-3 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)]"
                                    role="radiogroup"
                                    aria-labelledby={colorLabelId}
                                >
                                    {/* Color Swatches */}
                                    <div className="flex flex-wrap gap-2 justify-center w-full">
                                        {colors.map((c) => (
                                            <button
                                                key={c.value}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onChangeColor(c.value);
                                                }}
                                                className="group relative p-1"
                                                title={c.label}
                                                role="radio"
                                                aria-checked={subtitleColor === c.value}
                                                aria-label={c.label}
                                            >
                                                <div
                                                    className={`w-8 h-8 rounded-full border-2 shadow-sm transition-all duration-300 ease-out ${subtitleColor === c.value
                                                        ? 'border-white scale-110 ring-2 ring-white/20'
                                                        : 'border-transparent hover:scale-110 hover:border-white/30 opacity-80 hover:opacity-100'
                                                        }`}
                                                    style={{ backgroundColor: c.value }}
                                                />
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Karaoke Toggle (separate column, next to colors) */}
                        {onChangeKaraoke && karaokeSupported && (
                            <div className="flex-1 min-w-[200px]">
                                <label id={karaokeLabelId} className="block text-sm font-medium text-[var(--muted)] mb-3">
                                    {t('karaokeLabel')}
                                </label>
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onChangeKaraoke(!karaokeEnabled);
                                    }}
                                    role="switch"
                                    aria-checked={karaokeEnabled}
                                    aria-labelledby={karaokeLabelId}
                                    className={`w-full p-4 rounded-xl border text-left transition-all duration-300 flex items-center justify-between group h-[88px] ${karaokeEnabled
                                        ? 'border-[var(--accent)] bg-[var(--accent)]/10 shadow-[0_0_20px_rgba(var(--accent-rgb),0.15)]'
                                        : 'border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--surface-elevated)]'
                                        }`}
                                >
                                    <div className="flex flex-col gap-1">
                                        <div className={`font-medium text-sm transition-colors ${karaokeEnabled ? 'text-[var(--accent)]' : 'text-[var(--foreground)]'}`}>
                                            {t('karaokeMode')}
                                        </div>
                                        <div className="text-xs text-[var(--muted)]">
                                            {karaokeEnabled ? t('karaokeActive') : "Standard"}
                                        </div>
                                    </div>

                                    {/* Animated Icon instead of toggle switch */}
                                    <div className={`p-2 rounded-full transition-all duration-300 ${karaokeEnabled ? 'bg-[var(--accent)] text-black rotate-12 scale-110' : 'bg-[var(--surface-elevated)] text-[var(--muted)]'}`}>
                                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                                        </svg>
                                    </div>
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                {/* Visual Preview - Phone Mockup */}
                {!hidePreview && (
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
                            {/* Phone UI Elements - Semi-transparent overlays */}
                            {/* Notch/Dynamic Island */}
                            <div className="absolute top-3 left-1/2 -translate-x-1/2 w-16 h-4 bg-black/60 rounded-full blur-[0.5px] z-10" />

                            {/* Signal/Battery Icons (visual fake) */}
                            <div className="absolute top-3.5 right-4 flex gap-1 z-10">
                                <div className="w-4 h-2.5 bg-white/40 rounded-[2px]" />
                                <div className="w-0.5 h-1.5 bg-white/40 rounded-[1px] self-center" />
                            </div>

                            {/* Social Sidebar (Like/Comment/Share) */}
                            <div className="absolute bottom-20 right-3 w-7 flex flex-col gap-4 items-center z-10 pointer-events-none">
                                <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                                <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                                <div className="w-6 h-6 bg-white/30 rounded-full shadow-sm" />
                            </div>

                            {/* Social Bottom Info (username, caption) */}
                            <div className="absolute bottom-6 left-4 right-12 flex flex-col gap-2 z-10 pointer-events-none">
                                <div className="h-2.5 w-3/4 bg-white/30 rounded-full" />
                                <div className="h-2.5 w-1/2 bg-white/25 rounded-full" />
                            </div>

                            {/* Phone Content (Video or Thumbnail) */}
                            <div
                                className="absolute inset-0 bg-gray-900 cursor-pointer group"
                                onClick={() => togglePlay()}
                                role="button"
                                tabIndex={0}
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

                                        {/* Play/Pause Button Overlay - Only show when paused */}
                                        {!isPlaying && (
                                            <div className="absolute inset-0 flex items-center justify-center bg-black/30 animate-in fade-in z-30">
                                                <div className="w-12 h-12 bg-white/20 backdrop-blur-sm rounded-full flex items-center justify-center shadow-lg">
                                                    <svg className="w-6 h-6 text-white ml-1" viewBox="0 0 24 24" fill="currentColor">
                                                        <path d="M8 5v14l11-7z" />
                                                    </svg>
                                                </div>
                                            </div>
                                        )}

                                        {/* Custom Controls Bar - Appears on hover or when paused */}
                                        <div
                                            onClick={(e) => e.stopPropagation()} // Prevent play/pause when using controls
                                            className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-black/80 to-transparent z-40 flex flex-col justify-end pb-3 px-3 transition-opacity duration-200 opacity-0 group-hover:opacity-100"
                                        >
                                            <div className="flex items-center gap-2">
                                                {/* Play/Pause Mini Toggle */}
                                                <button
                                                    onClick={togglePlay}
                                                    className="w-5 h-5 flex items-center justify-center text-white hover:text-[var(--accent)] transition-colors"
                                                    aria-label={isPlaying ? (t('pausePreview') || 'Pause preview') : (t('playPreview') || 'Play preview')}
                                                    title={isPlaying ? (t('pausePreview') || 'Pause preview') : (t('playPreview') || 'Play preview')}
                                                >
                                                    {isPlaying ? (
                                                        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" /></svg>
                                                    ) : (
                                                        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                                                    )}
                                                </button>

                                                {/* Scrubber */}
                                                <div className="flex-1 h-8 flex items-center relative group/scrubber">
                                                    <input
                                                        aria-label={t('seekVideo') || 'Seek video'}
                                                        type="range"
                                                        min={0}
                                                        max={duration || 100}
                                                        value={currentTime}
                                                        onChange={handleSeek}
                                                        className="w-full h-1 bg-white/30 rounded-full appearance-none cursor-pointer
                                                            [&::-webkit-slider-thumb]:appearance-none
                                                            [&::-webkit-slider-thumb]:w-3
                                                            [&::-webkit-slider-thumb]:h-3
                                                            [&::-webkit-slider-thumb]:rounded-full
                                                            [&::-webkit-slider-thumb]:bg-[var(--accent)]
                                                            [&::-webkit-slider-thumb]:shadow-md
                                                            [&::-webkit-slider-thumb]:transition-transform
                                                            [&::-webkit-slider-thumb]:hover:scale-125"
                                                    />
                                                </div>

                                                {/* Mute Toggle */}
                                                <button
                                                    onClick={toggleMute}
                                                    className="w-5 h-5 flex items-center justify-center text-white hover:text-[var(--accent)] transition-colors"
                                                    aria-label={isMuted ? (t('unmutePreview') || 'Unmute preview') : (t('mutePreview') || 'Mute preview')}
                                                    title={isMuted ? (t('unmutePreview') || 'Unmute preview') : (t('mutePreview') || 'Mute preview')}
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
                                        {/* Static Thumbnail or Gradient */}
                                        {thumbnailUrl ? (
                                            <img
                                                src={thumbnailUrl}
                                                alt="Video preview"
                                                className="absolute inset-0 w-full h-full object-cover opacity-80"
                                            />
                                        ) : (
                                            <div className="absolute inset-0 bg-gradient-to-br from-purple-500/20 via-blue-500/20 to-purple-500/20" />
                                        )}

                                        {/* Static Text Preview */}
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

                                        {/* Optional: Small badge indicating waiting for subs if video selected? */}
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
                )}
            </div>
        </div>
    );
}
