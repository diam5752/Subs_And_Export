import React, { useRef, useState, useEffect, forwardRef, useImperativeHandle, memo } from 'react';
import { SubtitleOverlay, Cue } from './SubtitleOverlay';

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
    };
    onTimeUpdate?: (time: number) => void;
}

export const PreviewPlayer = memo(forwardRef<PreviewPlayerHandle, PreviewPlayerProps>(({
    videoUrl,
    cues,
    settings,
    onTimeUpdate
}, ref) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [currentTime, setCurrentTime] = useState(0);
    const [contentRect, setContentRect] = useState({ width: 1080, height: 1920, top: 0, left: 0 });

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
            const time = videoRef.current.currentTime;
            setCurrentTime(time);
            if (onTimeUpdate) onTimeUpdate(time);
        }
    };

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
                onLoadedMetadata={updateContentRect}
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
                <SubtitleOverlay
                    currentTime={currentTime}
                    cues={cues}
                    settings={settings}
                    videoWidth={contentRect.width}
                />
            </div>
        </div>
    );
}));

PreviewPlayer.displayName = 'PreviewPlayer';
