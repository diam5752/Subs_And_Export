import React, { useCallback, useEffect, useImperativeHandle, useRef, useState, forwardRef, memo, useMemo } from 'react';
import { SubtitleOverlay, Cue } from './SubtitleOverlay';
import { resegmentCues } from '../lib/subtitleUtils';

export interface PreviewPlayerHandle {
    seekTo: (time: number) => void;
}

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
}

export const PreviewPlayer = memo(forwardRef<PreviewPlayerHandle, PreviewPlayerProps>(({
    videoUrl,
    cues,
    settings,
    onTimeUpdate,
    initialTime = 0
}, ref) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [currentTime, setCurrentTime] = useState(initialTime);
    const [contentRect, setContentRect] = useState({ width: 1080, height: 1920, top: 0, left: 0 });
    const rafIdRef = useRef<number | null>(null);
    const frameCallbackIdRef = useRef<number | null>(null);
    const frameCallbackVideoRef = useRef<VideoWithFrameCallback | null>(null);
    const isTimeSyncRunningRef = useRef(false);

    type VideoWithFrameCallback = HTMLVideoElement & {
        requestVideoFrameCallback?: (
            callback: (now: DOMHighResTimeStamp, metadata: unknown) => void
        ) => number;
        cancelVideoFrameCallback?: (handle: number) => void;
    };

    useImperativeHandle(ref, () => ({
        seekTo: (time: number) => {
            if (videoRef.current) {
                videoRef.current.currentTime = time;
                setCurrentTime(time);
            }
        }
    }));

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
    const updateContentRect = () => {
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
    };

    useEffect(() => {
        const observer = new ResizeObserver(updateContentRect);
        if (containerRef.current) observer.observe(containerRef.current);
        window.addEventListener('resize', updateContentRect);

        return () => {
            observer.disconnect();
            window.removeEventListener('resize', updateContentRect);
        };
    }, []);

    // Set initial time when video loads or initialTime changes
    // Set initial time when video loads or initialTime changes
    useEffect(() => {
        if (typeof initialTime === 'number' && videoRef.current) {
            // Add slight offset (0.1s) to ensure renderer catches it, as requested
            const targetTime = initialTime + 0.1;

            // Seek if discrepancy > 0.1s to avoid fighting with playback
            if (Math.abs(videoRef.current.currentTime - targetTime) > 0.1) {
                videoRef.current.currentTime = targetTime;
                // eslint-disable-next-line react-hooks/set-state-in-effect
                setCurrentTime(targetTime);
            }
        }
    }, [initialTime]);

    // Force content rect update on mount to catch cached video metadata
    useEffect(() => {
        if (videoRef.current && videoRef.current.readyState >= 1) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            updateContentRect();
        }
    }, []);

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

    // 4. Transform cues (Split/Page if too long) matching backend logic
    const displayedCues = useMemo(() => {
        // Only run expensive re-segment logic if not 1-word-at-a-time mode
        if (settings.maxLines > 0) {
            // Import dynamically or assume it's available? It's in the same file as SubtitleOverlay? No, separate.
            // We need to import it. Since I can't add imports with replace_file easily, I'll rely on update helper.
            // Wait, I can't add imports here easily. I should check imports first.
            // Assuming I'll add the import in a separate step or it's available.
            return resegmentCues(cues, settings.maxLines, settings.fontSize);
        }
        return cues;
    }, [cues, settings.maxLines, settings.fontSize]);

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
                        const targetTime = initialTime + 0.1;
                        if (Math.abs(videoRef.current.currentTime - targetTime) > 0.1) {
                            videoRef.current.currentTime = targetTime;
                            setCurrentTime(targetTime);
                        }
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
                {/* Watermark Overlay */}
                {settings.watermarkEnabled && (
                    <div
                        className="absolute bottom-[40px] right-[40px] z-20 animate-in fade-in duration-500"
                        style={{ width: '15%' }} // Approximate 180px on 1080p
                    >
                        <img
                            src="/ascentia-logo.png"
                            alt="Watermark"
                            className="w-full h-auto opacity-90"
                        />
                    </div>
                )}

                {settings && (
                    <SubtitleOverlay
                        currentTime={currentTime}
                        cues={displayedCues}
                        settings={settings}
                        videoWidth={contentRect.width}
                    />
                )}
            </div>
        </div>
    );
}));

PreviewPlayer.displayName = 'PreviewPlayer';
