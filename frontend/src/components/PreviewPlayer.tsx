import React, { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef, memo } from 'react';
import Image from 'next/image';
import {
    SubtitleOverlay,
    Cue,
    type SubtitleTransformControls,
} from './SubtitleOverlay';
import type { InlineSubtitleEditorLabels } from './InlineSubtitleEditor';
import { findCueIndexAtTime } from '@/lib/subtitleUtils';

export interface PreviewPlayerHandle {
    seekTo: (time: number) => void;
    pause: () => void;
}

export interface InlineSubtitleEditorConfig {
    cues: Cue[];
    editingCueIndex: number | null;
    draftText: string;
    isSaving: boolean;
    error?: string | null;
    autoFocus?: boolean;
    labels: InlineSubtitleEditorLabels & { editAction: string };
    onBeginEdit: (index: number) => void;
    onChange: (text: string) => void;
    onSave: () => void;
    onCancel: () => void;
}

export type SubtitleTransformConfig = Omit<SubtitleTransformControls, 'onInteractionStart'>;

interface PreviewPlayerProps {
    videoUrl: string;
    cues: Cue[];
    settings: {
        position: number;
        color: string;
        fontSize: number;
        karaoke: boolean;
        maxLines: number;
        shadowStrength: number;
        watermarkEnabled?: boolean;
    };
    onTimeUpdate?: (time: number) => void;
    initialTime?: number;
    subtitleEditor?: InlineSubtitleEditorConfig;
    subtitleTransformControls?: SubtitleTransformConfig;
}

type VideoWithFrameCallback = HTMLVideoElement & {
    requestVideoFrameCallback?: (
        callback: (now: DOMHighResTimeStamp, metadata: unknown) => void
    ) => number;
    cancelVideoFrameCallback?: (handle: number) => void;
};

export const PreviewPlayer = memo(forwardRef<PreviewPlayerHandle, PreviewPlayerProps>(({
    videoUrl,
    cues,
    settings,
    onTimeUpdate,
    initialTime = 0,
    subtitleEditor,
    subtitleTransformControls,
}, ref) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [currentTime, setCurrentTime] = useState(initialTime);
    const [contentRect, setContentRect] = useState({ width: 1080, height: 1920, top: 0, left: 0 });
    const rafIdRef = useRef<number | null>(null);
    const frameCallbackIdRef = useRef<number | null>(null);
    const frameCallbackVideoRef = useRef<VideoWithFrameCallback | null>(null);
    const isTimeSyncRunningRef = useRef(false);

    const pauseForSubtitleInteraction = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;
        video.pause();
        setCurrentTime(video.currentTime);
    }, []);

    useImperativeHandle(ref, () => ({
        seekTo: (time: number) => {
            if (videoRef.current) {
                videoRef.current.currentTime = time;
                setCurrentTime(time);
            }
        },
        pause: () => {
            if (!videoRef.current) return;
            videoRef.current.pause();
            setCurrentTime(videoRef.current.currentTime);
        },
    }));

    const editableCues = subtitleEditor?.cues;
    const activeEditableCueIndex = useMemo(() => {
        if (!editableCues?.length) return -1;
        return findCueIndexAtTime(editableCues, currentTime);
    }, [currentTime, editableCues]);

    const inlineEditor = useMemo(() => {
        if (!subtitleEditor || activeEditableCueIndex < 0) return undefined;
        if (
            subtitleEditor.editingCueIndex !== null
            && subtitleEditor.editingCueIndex !== activeEditableCueIndex
        ) {
            return undefined;
        }

        return {
            cueIndex: activeEditableCueIndex,
            isEditing: subtitleEditor.editingCueIndex === activeEditableCueIndex,
            draftText: subtitleEditor.draftText,
            isSaving: subtitleEditor.isSaving,
            error: subtitleEditor.error,
            autoFocus: subtitleEditor.autoFocus,
            labels: subtitleEditor.labels,
            onBeginEdit: () => {
                pauseForSubtitleInteraction();
                subtitleEditor.onBeginEdit(activeEditableCueIndex);
            },
            onChange: subtitleEditor.onChange,
            onSave: subtitleEditor.onSave,
            onCancel: subtitleEditor.onCancel,
        };
    }, [activeEditableCueIndex, pauseForSubtitleInteraction, subtitleEditor]);

    const overlayTransformControls = useMemo<SubtitleTransformControls | undefined>(() => {
        if (!subtitleTransformControls) return undefined;
        return {
            ...subtitleTransformControls,
            onInteractionStart: pauseForSubtitleInteraction,
        };
    }, [pauseForSubtitleInteraction, subtitleTransformControls]);

    // Handle time update from video
    const handleTimeUpdate = () => {
        if (videoRef.current) {
            if (onTimeUpdate) onTimeUpdate(videoRef.current.currentTime);
        }
    };

    const stopHighResTimeSync = useCallback(() => {
        const video = (frameCallbackVideoRef.current ?? (videoRef.current as VideoWithFrameCallback | null));

        if (frameCallbackIdRef.current !== null && video?.cancelVideoFrameCallback) {
            video.cancelVideoFrameCallback(frameCallbackIdRef.current);
        }
        frameCallbackIdRef.current = null;
        frameCallbackVideoRef.current = null;

        if (rafIdRef.current !== null) {
            cancelAnimationFrame(rafIdRef.current);
        }
        rafIdRef.current = null;
        isTimeSyncRunningRef.current = false;
    }, []);

    const startHighResTimeSync = useCallback(() => {
        const video = videoRef.current as VideoWithFrameCallback | null;
        if (!video || isTimeSyncRunningRef.current) return;
        isTimeSyncRunningRef.current = true;
        frameCallbackVideoRef.current = video;

        const sync = () => {
            const currentVideo = videoRef.current as VideoWithFrameCallback | null;
            if (!currentVideo) {
                stopHighResTimeSync();
                return;
            }

            setCurrentTime(currentVideo.currentTime);

            if (currentVideo.paused || currentVideo.ended) {
                stopHighResTimeSync();
                return;
            }

            if (currentVideo.requestVideoFrameCallback) {
                frameCallbackIdRef.current = currentVideo.requestVideoFrameCallback(() => sync());
            } else {
                rafIdRef.current = requestAnimationFrame(sync);
            }
        };

        if (video.requestVideoFrameCallback) {
            frameCallbackIdRef.current = video.requestVideoFrameCallback(() => sync());
        } else {
            rafIdRef.current = requestAnimationFrame(sync);
        }
    }, [stopHighResTimeSync]);

    // Calculate actual video position within the container (object-contain logic)
    const updateContentRect = useCallback(() => {
        if (!videoRef.current || !containerRef.current) return;

        const video = videoRef.current;
        const container = containerRef.current;

        const vW = video.videoWidth || 1080;
        const vH = video.videoHeight || 1920;
        const cW = container.clientWidth;
        const cH = container.clientHeight;

        if (vW === 0 || vH === 0) return;

        const videoAspect = vW / vH;
        const containerAspect = cW / cH;

        let renderW, renderH, renderTop, renderLeft;

        // Container is WIDER than video (Pillarbox)
        if (containerAspect > videoAspect) {
            renderH = cH;
            renderW = cH * videoAspect;
            renderTop = 0;
            renderLeft = (cW - renderW) / 2;
        }
        // Container is TALLER than video (Letterbox)
        else {
            renderW = cW;
            renderH = cW / videoAspect;
            renderLeft = 0;
            renderTop = (cH - renderH) / 2;
        }

        setContentRect({
            width: renderW,
            height: renderH,
            top: renderTop,
            left: renderLeft
        });
    }, []);

    useEffect(() => {
        const observer = new ResizeObserver(updateContentRect);
        if (containerRef.current) observer.observe(containerRef.current);
        window.addEventListener('resize', updateContentRect);

        return () => {
            observer.disconnect();
            window.removeEventListener('resize', updateContentRect);
        };
    }, [updateContentRect]);

    // Set initial time when video loads or initialTime changes
    useEffect(() => {
        if (typeof initialTime === 'number' && videoRef.current) {
            if (Math.abs(videoRef.current.currentTime - initialTime) > 0.01) {
                videoRef.current.currentTime = initialTime;
            }
        }
    }, [initialTime]);

    useEffect(() => {
        const video = videoRef.current as VideoWithFrameCallback | null;
        if (!video) return;

        const handlePlay = () => startHighResTimeSync();
        const handlePause = () => {
            setCurrentTime(video.currentTime);
            stopHighResTimeSync();
        };
        const handleSeeked = () => setCurrentTime(video.currentTime);
        const handleEnded = () => {
            setCurrentTime(video.currentTime);
            stopHighResTimeSync();
        };

        video.addEventListener('play', handlePlay);
        video.addEventListener('pause', handlePause);
        video.addEventListener('seeked', handleSeeked);
        video.addEventListener('ended', handleEnded);

        if (!video.paused && !video.ended) startHighResTimeSync();

        return () => {
            stopHighResTimeSync();
            video.removeEventListener('play', handlePlay);
            video.removeEventListener('pause', handlePause);
            video.removeEventListener('seeked', handleSeeked);
            video.removeEventListener('ended', handleEnded);
        };
    }, [startHighResTimeSync, stopHighResTimeSync]);

    // OPTIMIZATION: Removed redundant re-segmentation logic.
    // The cues passed to PreviewPlayer are expected to be already processed/segmented
    // by the parent (ProcessContext). This saves a duplicate canvas text measurement loop.

    return (
        <div
            ref={containerRef}
            className="relative w-full h-full bg-black rounded-xl overflow-hidden shadow-lg border border-white/10"
        >
            <video
                ref={videoRef}
                src={videoUrl}
                className="w-full h-full object-contain"
                controls
                playsInline
                onTimeUpdate={handleTimeUpdate}
                onLoadedMetadata={() => {
                    updateContentRect();
                    if (typeof initialTime === 'number' && videoRef.current) {
                        if (Math.abs(videoRef.current.currentTime - initialTime) > 0.01) {
                            videoRef.current.currentTime = initialTime;
                        }
                        setCurrentTime(videoRef.current.currentTime);
                    }
                }}
            />

            <div
                style={{
                    position: 'absolute',
                    top: contentRect.top,
                    left: contentRect.left,
                    width: contentRect.width,
                    height: contentRect.height,
                    pointerEvents: 'none'
                }}
            >
                {/* Watermark Overlay */}
                {settings.watermarkEnabled && (
                    <div
                        className="absolute bottom-[40px] right-[40px] z-20 w-[15%] animate-in fade-in duration-500"
                    >
                        <Image
                            src="/ascentia-logo.png"
                            alt="Watermark"
                            width={1280}
                            height={1280}
                            sizes="20vw"
                            className="w-full h-auto opacity-90"
                        />
                    </div>
                )}

                <SubtitleOverlay
                    currentTime={currentTime}
                    cues={cues}
                    settings={settings}
                    videoWidth={contentRect.width}
                    videoHeight={contentRect.height}
                    inlineEditor={inlineEditor}
                    transformControls={overlayTransformControls}
                />
            </div>
        </div>
    );
}));

PreviewPlayer.displayName = 'PreviewPlayer';
