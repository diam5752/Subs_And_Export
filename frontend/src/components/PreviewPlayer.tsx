import React, { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef, memo } from 'react';
import Image from 'next/image';
import {
    SubtitleOverlay,
    Cue,
    type SubtitleTransformControls,
} from './SubtitleOverlay';
import type { InlineSubtitleEditorLabels } from './InlineSubtitleEditor';
import { findCueIndexAtTime } from '@/lib/subtitleUtils';
import { BRAND } from '@/lib/brand';

export interface PreviewPlayerHandle {
    seekTo: (time: number) => void;
    pause: () => void;
    togglePlayback: () => void;
    toggleMuted: () => void;
}

interface PreviewPlaybackStatus {
    duration: number;
    isPlaying: boolean;
    isMuted: boolean;
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
    playbackToggleLabel?: string;
    onPlaybackStatusChange?: (status: PreviewPlaybackStatus) => void;
}

type VideoWithFrameCallback = HTMLVideoElement & {
    requestVideoFrameCallback?: (
        callback: (now: DOMHighResTimeStamp, metadata: unknown) => void
    ) => number;
    cancelVideoFrameCallback?: (handle: number) => void;
};

type PreviewGestureMode = 'pending' | 'seeking' | 'speed' | 'cancelled';

type PreviewGesture = {
    pointerId: number;
    startX: number;
    startY: number;
    startTime: number;
    wasPlaying: boolean;
    originalPlaybackRate: number;
    dragThreshold: number;
    mode: PreviewGestureMode;
};

type StageTouchPoint = {
    x: number;
    y: number;
};

type StagePinchGesture = {
    pointerIds: readonly [number, number];
    startDistance: number;
    startSize: number;
    moved: boolean;
};

type PendingPlaybackCommand = {
    id: number;
    kind: 'play' | 'pause';
};

type GestureFeedback =
    | { kind: 'seek'; currentTime: number; delta: number; duration: number }
    | { kind: 'speed' };

const GESTURE_DRAG_THRESHOLD_PX = 8;
const TOUCH_GESTURE_DRAG_THRESHOLD_PX = 14;
const PINCH_DRAG_THRESHOLD_PX = 3;
const SUBTITLE_SIZE_MIN = 50;
const SUBTITLE_SIZE_MAX = 150;
const LONG_PRESS_DELAY_MS = 500;
const PREVIEW_SPEED_RATE = 2;
const FIRST_FRAME_PRIME_TIME_SECONDS = 0.001;

function clamp(value: number, minimum: number, maximum: number): number {
    return Math.min(maximum, Math.max(minimum, value));
}

function formatGestureTime(seconds: number): string {
    const safeSeconds = Number.isFinite(seconds) && seconds > 0
        ? Math.floor(seconds)
        : 0;
    const minutes = Math.floor(safeSeconds / 60);
    const remainingSeconds = safeSeconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
}

function seekSpanForDuration(duration: number): number {
    if (!Number.isFinite(duration) || duration <= 0) return 0;
    return Math.min(60, Math.max(15, duration * 0.25));
}

function distanceBetween(first: StageTouchPoint, second: StageTouchPoint): number {
    return Math.hypot(second.x - first.x, second.y - first.y);
}

export const PreviewPlayer = memo(forwardRef<PreviewPlayerHandle, PreviewPlayerProps>(({
    videoUrl,
    cues,
    settings,
    onTimeUpdate,
    initialTime = 0,
    subtitleEditor,
    subtitleTransformControls,
    playbackToggleLabel = 'Toggle video playback',
    onPlaybackStatusChange,
}, ref) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [currentTime, setCurrentTime] = useState(initialTime);
    const [contentRect, setContentRect] = useState({ width: 1080, height: 1920, top: 0, left: 0 });
    const rafIdRef = useRef<number | null>(null);
    const frameCallbackIdRef = useRef<number | null>(null);
    const frameCallbackVideoRef = useRef<VideoWithFrameCallback | null>(null);
    const isTimeSyncRunningRef = useRef(false);
    const gestureRef = useRef<PreviewGesture | null>(null);
    const longPressTimerRef = useRef<number | null>(null);
    const playbackIntentRef = useRef<boolean | null>(null);
    const playbackRequestIdRef = useRef(0);
    const pendingPlaybackCommandRef = useRef<PendingPlaybackCommand | null>(null);
    const stageTouchPointsRef = useRef<Map<number, StageTouchPoint>>(new Map());
    const stagePinchRef = useRef<StagePinchGesture | null>(null);
    const suppressStageClickRef = useRef(false);
    const latestSubtitleSizeRef = useRef(settings.fontSize);
    const [subtitleGestureResetToken, setSubtitleGestureResetToken] = useState(0);
    const [gestureFeedback, setGestureFeedback] = useState<GestureFeedback | null>(null);
    latestSubtitleSizeRef.current = settings.fontSize;

    const reportPlaybackStatus = useCallback(() => {
        const video = videoRef.current;
        if (!video || !onPlaybackStatusChange) return;
        onPlaybackStatusChange({
            duration: Number.isFinite(video.duration) ? video.duration : 0,
            isPlaying: !video.paused && !video.ended,
            isMuted: video.muted,
        });
    }, [onPlaybackStatusChange]);

    const requestPlay = useCallback((onRejected?: () => void) => {
        const video = videoRef.current;
        if (!video) return;

        const requestId = playbackRequestIdRef.current + 1;
        playbackRequestIdRef.current = requestId;
        playbackIntentRef.current = true;
        pendingPlaybackCommandRef.current = { id: requestId, kind: 'play' };

        let playRequest: Promise<void>;
        try {
            playRequest = video.play();
        } catch {
            if (playbackRequestIdRef.current === requestId) {
                playbackIntentRef.current = false;
                pendingPlaybackCommandRef.current = null;
                onRejected?.();
                reportPlaybackStatus();
            }
            return;
        }

        void playRequest.then(() => {
            const pendingCommand = pendingPlaybackCommandRef.current;
            if (pendingCommand?.id === requestId && pendingCommand.kind === 'play') {
                pendingPlaybackCommandRef.current = null;
            }
        }).catch(() => {
            if (
                playbackRequestIdRef.current !== requestId
                || playbackIntentRef.current !== true
            ) {
                return;
            }

            playbackIntentRef.current = false;
            pendingPlaybackCommandRef.current = null;
            onRejected?.();
            reportPlaybackStatus();
        });
    }, [reportPlaybackStatus]);

    const requestPause = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;
        const previousCommand = pendingPlaybackCommandRef.current;
        const requestId = playbackRequestIdRef.current + 1;
        playbackRequestIdRef.current = requestId;
        playbackIntentRef.current = false;
        pendingPlaybackCommandRef.current = { id: requestId, kind: 'pause' };
        const wasAlreadyPaused = video.paused;
        video.pause();
        if (
            wasAlreadyPaused
            && previousCommand?.kind !== 'play'
            && pendingPlaybackCommandRef.current?.id === requestId
        ) {
            pendingPlaybackCommandRef.current = null;
        }
    }, []);

    const togglePlayback = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;

        const isPlayingOrRequested = playbackIntentRef.current
            ?? (!video.paused && !video.ended);
        if (!isPlayingOrRequested) {
            if (video.ended) {
                video.currentTime = 0;
                setCurrentTime(0);
            }
            requestPlay();
            return;
        }

        requestPause();
    }, [requestPause, requestPlay]);

    const toggleMuted = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;
        video.muted = !video.muted;
        reportPlaybackStatus();
    }, [reportPlaybackStatus]);

    const clearLongPressTimer = useCallback(() => {
        if (longPressTimerRef.current !== null) {
            window.clearTimeout(longPressTimerRef.current);
            longPressTimerRef.current = null;
        }
    }, []);

    const handlePreviewPointerDown = useCallback((
        event: React.PointerEvent<HTMLVideoElement>,
    ) => {
        if (event.button !== 0 || event.isPrimary === false) return;

        const video = videoRef.current;
        if (!video) return;

        clearLongPressTimer();
        setGestureFeedback(null);
        gestureRef.current = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            startTime: video.currentTime,
            wasPlaying: playbackIntentRef.current ?? (!video.paused && !video.ended),
            originalPlaybackRate: video.playbackRate,
            dragThreshold: event.pointerType === 'touch'
                ? TOUCH_GESTURE_DRAG_THRESHOLD_PX
                : GESTURE_DRAG_THRESHOLD_PX,
            mode: 'pending',
        };

        try {
            event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
            // Pointer capture is best-effort on older browsers.
        }

        longPressTimerRef.current = window.setTimeout(() => {
            const gesture = gestureRef.current;
            const activeVideo = videoRef.current;
            if (
                !gesture
                || gesture.pointerId !== event.pointerId
                || gesture.mode !== 'pending'
                || !activeVideo
            ) {
                return;
            }

            gesture.mode = 'speed';
            activeVideo.playbackRate = PREVIEW_SPEED_RATE;
            setGestureFeedback({ kind: 'speed' });
            try {
                activeVideo.setPointerCapture(event.pointerId);
            } catch {
                // Pointer capture is best-effort on older mobile browsers.
            }

            if (!gesture.wasPlaying) {
                requestPlay(() => {
                    activeVideo.playbackRate = gesture.originalPlaybackRate;
                    gesture.mode = 'cancelled';
                    setGestureFeedback(null);
                });
            }
        }, LONG_PRESS_DELAY_MS);
    }, [clearLongPressTimer, requestPlay]);

    const handlePreviewPointerMove = useCallback((
        event: React.PointerEvent<HTMLVideoElement>,
    ) => {
        const gesture = gestureRef.current;
        const video = videoRef.current;
        if (!gesture || !video || gesture.pointerId !== event.pointerId) return;

        const deltaX = event.clientX - gesture.startX;
        const deltaY = event.clientY - gesture.startY;

        if (gesture.mode === 'pending') {
            if (Math.hypot(deltaX, deltaY) < gesture.dragThreshold) return;

            clearLongPressTimer();
            if (Math.abs(deltaX) <= Math.abs(deltaY)) {
                gesture.mode = 'cancelled';
                return;
            }

            gesture.mode = 'seeking';
            requestPause();
            try {
                event.currentTarget.setPointerCapture(event.pointerId);
            } catch {
                // Pointer capture is best-effort on older mobile browsers.
            }
        }

        if (gesture.mode !== 'seeking') return;

        event.preventDefault();
        const duration = Number.isFinite(video.duration) ? video.duration : 0;
        const seekSpan = seekSpanForDuration(duration);
        if (seekSpan <= 0) return;

        const width = Math.max(
            1,
            event.currentTarget.getBoundingClientRect().width
                || event.currentTarget.clientWidth,
        );
        const nextTime = clamp(
            gesture.startTime + ((deltaX / width) * seekSpan),
            0,
            duration,
        );

        video.currentTime = nextTime;
        setCurrentTime(nextTime);
        onTimeUpdate?.(nextTime);
        setGestureFeedback({
            kind: 'seek',
            currentTime: nextTime,
            delta: nextTime - gesture.startTime,
            duration,
        });
    }, [clearLongPressTimer, onTimeUpdate, requestPause]);

    const finishPreviewGesture = useCallback((
        event: React.PointerEvent<HTMLVideoElement>,
        cancelled = false,
    ) => {
        const gesture = gestureRef.current;
        const video = videoRef.current;
        if (!gesture || !video || gesture.pointerId !== event.pointerId) return;

        clearLongPressTimer();

        try {
            if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
                event.currentTarget.releasePointerCapture(event.pointerId);
            }
        } catch {
            // Pointer capture may already be gone after a browser-level gesture.
        }

        if (gesture.mode === 'pending' && !cancelled) {
            togglePlayback();
        } else if (gesture.mode === 'seeking' && gesture.wasPlaying && !cancelled) {
            requestPlay();
        } else if (gesture.mode === 'speed') {
            video.playbackRate = gesture.originalPlaybackRate;
            if (!gesture.wasPlaying) {
                requestPause();
                setCurrentTime(video.currentTime);
            }
            reportPlaybackStatus();
        }

        gestureRef.current = null;
        setGestureFeedback(null);
    }, [clearLongPressTimer, reportPlaybackStatus, requestPause, requestPlay, togglePlayback]);

    useEffect(() => () => {
        clearLongPressTimer();
        playbackRequestIdRef.current += 1;
        playbackIntentRef.current = null;
        pendingPlaybackCommandRef.current = null;
        stagePinchRef.current = null;
        stageTouchPointsRef.current.clear();
        suppressStageClickRef.current = false;
        const gesture = gestureRef.current;
        const video = videoRef.current;
        if (gesture && video) {
            video.playbackRate = gesture.originalPlaybackRate;
        }
        gestureRef.current = null;
    }, [clearLongPressTimer]);

    const pauseForSubtitleInteraction = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;
        requestPause();
        setCurrentTime(video.currentTime);
    }, [requestPause]);

    const hasActiveTransformCue = useMemo(
        () => findCueIndexAtTime(cues, currentTime) >= 0,
        [cues, currentTime],
    );

    const cancelPreviewGestureForPinch = useCallback(() => {
        clearLongPressTimer();
        const gesture = gestureRef.current;
        const video = videoRef.current;

        if (gesture && video) {
            if (gesture.mode === 'speed') {
                video.playbackRate = gesture.originalPlaybackRate;
            } else if (
                gesture.mode === 'seeking'
                && Math.abs(video.currentTime - gesture.startTime) > 0.001
            ) {
                video.currentTime = gesture.startTime;
                setCurrentTime(gesture.startTime);
                onTimeUpdate?.(gesture.startTime);
            }
        }

        gestureRef.current = null;
        setGestureFeedback(null);
    }, [clearLongPressTimer, onTimeUpdate]);

    const finishStagePinch = useCallback((cancelled: boolean) => {
        const pinch = stagePinchRef.current;
        stagePinchRef.current = null;
        stageTouchPointsRef.current.clear();
        suppressStageClickRef.current = !cancelled;
        setSubtitleGestureResetToken((token) => token + 1);

        const stage = containerRef.current;
        if (!stage || !pinch) return;
        for (const pointerId of pinch.pointerIds) {
            try {
                if (stage.hasPointerCapture?.(pointerId)) {
                    stage.releasePointerCapture(pointerId);
                }
            } catch {
                // Capture may already be gone after a WebKit interruption.
            }
        }
    }, []);

    const handleStagePointerDownCapture = useCallback((
        event: React.PointerEvent<HTMLDivElement>,
    ) => {
        if (event.pointerType !== 'touch') return;

        if (stageTouchPointsRef.current.size === 0) {
            // A genuine new pointer sequence must not inherit click suppression
            // from a completed pinch that produced no synthetic click.
            suppressStageClickRef.current = false;
        }

        if (!subtitleTransformControls || !hasActiveTransformCue) return;
        stageTouchPointsRef.current.set(event.pointerId, {
            x: event.clientX,
            y: event.clientY,
        });

        if (stagePinchRef.current) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }

        if (stageTouchPointsRef.current.size !== 2) return;
        const points = Array.from(stageTouchPointsRef.current.entries());
        const first = points[0];
        const second = points[1];
        stagePinchRef.current = {
            pointerIds: [first[0], second[0]],
            startDistance: Math.max(1, distanceBetween(first[1], second[1])),
            startSize: latestSubtitleSizeRef.current,
            moved: false,
        };

        event.preventDefault();
        event.stopPropagation();
        cancelPreviewGestureForPinch();
        pauseForSubtitleInteraction();
        setSubtitleGestureResetToken((token) => token + 1);

        for (const pointerId of stagePinchRef.current.pointerIds) {
            try {
                event.currentTarget.setPointerCapture(pointerId);
            } catch {
                // Pointer capture is best-effort on older mobile browsers.
            }
        }
    }, [
        cancelPreviewGestureForPinch,
        hasActiveTransformCue,
        pauseForSubtitleInteraction,
        subtitleTransformControls,
    ]);

    const handleStagePointerMoveCapture = useCallback((
        event: React.PointerEvent<HTMLDivElement>,
    ) => {
        if (
            event.pointerType === 'touch'
            && stageTouchPointsRef.current.has(event.pointerId)
        ) {
            stageTouchPointsRef.current.set(event.pointerId, {
                x: event.clientX,
                y: event.clientY,
            });
        }

        const pinch = stagePinchRef.current;
        if (
            !pinch
            || !subtitleTransformControls
            || !pinch.pointerIds.includes(event.pointerId)
        ) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        const first = stageTouchPointsRef.current.get(pinch.pointerIds[0]);
        const second = stageTouchPointsRef.current.get(pinch.pointerIds[1]);
        if (!first || !second) return;

        const distance = distanceBetween(first, second);
        if (
            !pinch.moved
            && Math.abs(distance - pinch.startDistance) < PINCH_DRAG_THRESHOLD_PX
        ) {
            return;
        }

        pinch.moved = true;
        subtitleTransformControls.onSizeChange(Math.round(clamp(
            pinch.startSize * (distance / pinch.startDistance),
            SUBTITLE_SIZE_MIN,
            SUBTITLE_SIZE_MAX,
        )));
    }, [subtitleTransformControls]);

    const finishStagePointer = useCallback((
        event: React.PointerEvent<HTMLDivElement>,
        cancelled: boolean,
    ) => {
        if (event.pointerType !== 'touch') return;

        const pinch = stagePinchRef.current;
        if (pinch?.pointerIds.includes(event.pointerId)) {
            event.preventDefault();
            event.stopPropagation();
            finishStagePinch(cancelled);
            return;
        }

        stageTouchPointsRef.current.delete(event.pointerId);
    }, [finishStagePinch]);

    const handleStageLostPointerCapture = useCallback((
        event: React.PointerEvent<HTMLDivElement>,
    ) => {
        // Transferring capture from the video or subtitle child to the stage
        // legitimately emits a bubbling lostpointercapture on that child.
        // Only loss of capture owned by the stage interrupts the shared pinch.
        if (event.target !== event.currentTarget) return;
        if (stagePinchRef.current?.pointerIds.includes(event.pointerId)) {
            finishStagePinch(true);
            return;
        }
        stageTouchPointsRef.current.delete(event.pointerId);
    }, [finishStagePinch]);

    const handleStageClickCapture = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
        if (!suppressStageClickRef.current) return;
        event.preventDefault();
        event.stopPropagation();
        suppressStageClickRef.current = false;
    }, []);

    useEffect(() => {
        const interruptGestures = () => {
            if (stagePinchRef.current) {
                finishStagePinch(true);
            } else {
                stageTouchPointsRef.current.clear();
            }
        };
        const handleVisibilityChange = () => {
            if (document.visibilityState === 'hidden') interruptGestures();
        };

        window.addEventListener('blur', interruptGestures);
        document.addEventListener('visibilitychange', handleVisibilityChange);
        return () => {
            window.removeEventListener('blur', interruptGestures);
            document.removeEventListener('visibilitychange', handleVisibilityChange);
        };
    }, [finishStagePinch]);

    useEffect(() => {
        playbackRequestIdRef.current += 1;
        playbackIntentRef.current = null;
        pendingPlaybackCommandRef.current = null;
    }, [videoUrl]);

    useImperativeHandle(ref, () => ({
        seekTo: (time: number) => {
            if (videoRef.current) {
                videoRef.current.currentTime = time;
                setCurrentTime(time);
            }
        },
        pause: () => {
            if (!videoRef.current) return;
            requestPause();
            setCurrentTime(videoRef.current.currentTime);
        },
        togglePlayback,
        toggleMuted,
    }), [requestPause, toggleMuted, togglePlayback]);

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

        const handlePlay = () => {
            const pendingCommand = pendingPlaybackCommandRef.current;
            if (
                playbackIntentRef.current === false
                && pendingCommand?.kind === 'pause'
            ) {
                // A queued play event from an older request lost the race to a
                // newer pause command. Keep the latest user intent authoritative.
                video.pause();
                return;
            }

            playbackIntentRef.current = true;
            if (pendingCommand?.kind === 'play') {
                pendingPlaybackCommandRef.current = null;
            }
            startHighResTimeSync();
            reportPlaybackStatus();
        };
        const handlePause = () => {
            const pendingCommand = pendingPlaybackCommandRef.current;
            if (
                playbackIntentRef.current === true
                && pendingCommand?.kind === 'play'
            ) {
                // A delayed pause event from the previous command must not
                // overwrite a newer play request that is still settling.
                return;
            }

            playbackRequestIdRef.current += 1;
            playbackIntentRef.current = false;
            pendingPlaybackCommandRef.current = null;
            setCurrentTime(video.currentTime);
            stopHighResTimeSync();
            reportPlaybackStatus();
        };
        const handleSeeked = () => setCurrentTime(video.currentTime);
        const handleEnded = () => {
            playbackRequestIdRef.current += 1;
            playbackIntentRef.current = false;
            pendingPlaybackCommandRef.current = null;
            setCurrentTime(video.currentTime);
            stopHighResTimeSync();
            reportPlaybackStatus();
        };
        const handleDurationChange = () => reportPlaybackStatus();
        const handleVolumeChange = () => reportPlaybackStatus();

        video.addEventListener('play', handlePlay);
        video.addEventListener('pause', handlePause);
        video.addEventListener('seeked', handleSeeked);
        video.addEventListener('ended', handleEnded);
        video.addEventListener('durationchange', handleDurationChange);
        video.addEventListener('volumechange', handleVolumeChange);

        if (!video.paused && !video.ended) startHighResTimeSync();
        reportPlaybackStatus();

        return () => {
            stopHighResTimeSync();
            video.removeEventListener('play', handlePlay);
            video.removeEventListener('pause', handlePause);
            video.removeEventListener('seeked', handleSeeked);
            video.removeEventListener('ended', handleEnded);
            video.removeEventListener('durationchange', handleDurationChange);
            video.removeEventListener('volumechange', handleVolumeChange);
        };
    }, [reportPlaybackStatus, startHighResTimeSync, stopHighResTimeSync]);

    // OPTIMIZATION: Removed redundant re-segmentation logic.
    // The cues passed to PreviewPlayer are expected to be already processed/segmented
    // by the parent (ProcessContext). This saves a duplicate canvas text measurement loop.
    const seekProgress = gestureFeedback?.kind === 'seek' && gestureFeedback.duration > 0
        ? clamp((gestureFeedback.currentTime / gestureFeedback.duration) * 100, 0, 100)
        : 0;

    return (
        <div
            ref={containerRef}
            className="preview-gesture-surface relative w-full h-full bg-black rounded-xl overflow-hidden shadow-lg border border-white/10"
            data-subtitle-pinch-enabled={
                subtitleTransformControls && hasActiveTransformCue ? 'true' : 'false'
            }
            onPointerDownCapture={handleStagePointerDownCapture}
            onPointerMoveCapture={handleStagePointerMoveCapture}
            onPointerUpCapture={(event) => finishStagePointer(event, false)}
            onPointerCancelCapture={(event) => finishStagePointer(event, true)}
            onLostPointerCapture={handleStageLostPointerCapture}
            onClickCapture={handleStageClickCapture}
        >
            <video
                ref={videoRef}
                src={videoUrl}
                className="preview-video h-full w-full cursor-pointer object-contain"
                playsInline
                preload="metadata"
                draggable={false}
                disablePictureInPicture
                disableRemotePlayback
                controlsList="nodownload noplaybackrate noremoteplayback"
                role="button"
                tabIndex={0}
                aria-label={playbackToggleLabel}
                onPointerDown={handlePreviewPointerDown}
                onPointerMove={handlePreviewPointerMove}
                onPointerUp={(event) => finishPreviewGesture(event)}
                onPointerCancel={(event) => finishPreviewGesture(event, true)}
                onContextMenu={(event) => event.preventDefault()}
                onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        togglePlayback();
                    }
                }}
                onTimeUpdate={handleTimeUpdate}
                onLoadedMetadata={() => {
                    updateContentRect();
                    if (typeof initialTime === 'number' && videoRef.current) {
                        const video = videoRef.current;
                        const shouldPrimeFirstFrame = initialTime <= 0
                            && video.paused
                            && video.currentTime === 0
                            && Number.isFinite(video.duration)
                            && video.duration > 0;

                        if (shouldPrimeFirstFrame) {
                            // WebKit only fetches metadata for a paused video at 0:00.
                            // A tiny seek requests and paints the first frame without
                            // autoplaying or preloading the complete media file.
                            video.currentTime = Math.min(
                                FIRST_FRAME_PRIME_TIME_SECONDS,
                                video.duration / 2,
                            );
                        } else if (Math.abs(video.currentTime - initialTime) > 0.01) {
                            video.currentTime = initialTime;
                        }
                        setCurrentTime(video.currentTime);
                    }
                    reportPlaybackStatus();
                }}
            />

            {gestureFeedback?.kind === 'speed' && (
                <div
                    className="preview-gesture-feedback"
                    data-kind="speed"
                    data-testid="preview-gesture-feedback"
                    role="status"
                    aria-live="polite"
                >
                    2×
                </div>
            )}

            {gestureFeedback?.kind === 'seek' && (
                <div
                    className="preview-seek-feedback"
                    data-progress={Math.round(seekProgress)}
                    data-testid="preview-gesture-feedback"
                    role="status"
                    aria-live="polite"
                >
                    <div className="preview-seek-feedback-copy">
                        <strong>
                            {gestureFeedback.delta >= 0 ? '+' : '−'}
                            {formatGestureTime(Math.abs(gestureFeedback.delta))}
                        </strong>
                        <span>
                            {formatGestureTime(gestureFeedback.currentTime)}
                            {' / '}
                            {formatGestureTime(gestureFeedback.duration)}
                        </span>
                        <span>
                            −{formatGestureTime(
                                Math.max(
                                    0,
                                    gestureFeedback.duration - gestureFeedback.currentTime,
                                ),
                            )}
                        </span>
                    </div>
                    <div className="preview-seek-track" aria-hidden="true">
                        <span
                            className="preview-seek-progress"
                            data-testid="preview-seek-progress"
                            style={{ width: `${seekProgress}%` }}
                        />
                        <span
                            className="preview-seek-thumb"
                            style={{ left: `${seekProgress}%` }}
                        />
                    </div>
                </div>
            )}

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
                        className="absolute bottom-[40px] right-[40px] z-20 w-[30%] animate-in fade-in duration-500"
                    >
                        <Image
                            src={BRAND.assets.watermark}
                            alt="gsubs watermark"
                            width={1360}
                            height={304}
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
                    gestureResetToken={subtitleGestureResetToken}
                />
            </div>
        </div>
    );
}));

PreviewPlayer.displayName = 'PreviewPlayer';
