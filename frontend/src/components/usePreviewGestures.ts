import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MouseEvent as ReactMouseEvent,
  type MutableRefObject,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  type SetStateAction,
} from "react";
import type { Cue } from "./SubtitleOverlay";
import type { SubtitleTransformConfig } from "./PreviewPlayerTypes";
import { clamp, type GestureFeedback } from "./previewPlayerSupport";
import { findCueIndexAtTime } from "@/lib/subtitleUtils";

type PreviewGestureMode = "pending" | "seeking" | "speed" | "cancelled";

interface PreviewGesture {
  pointerId: number;
  startX: number;
  startY: number;
  startTime: number;
  wasPlaying: boolean;
  originalPlaybackRate: number;
  dragThreshold: number;
  mode: PreviewGestureMode;
}

interface StageTouchPoint {
  x: number;
  y: number;
}

interface StagePinchGesture {
  pointerIds: readonly [number, number];
  startDistance: number;
  startSize: number;
  moved: boolean;
}

interface UsePreviewGesturesOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  containerRef: RefObject<HTMLDivElement | null>;
  cues: Cue[];
  currentTime: number;
  fontSize: number;
  subtitleTransformControls?: SubtitleTransformConfig;
  onTimeUpdate?: (time: number) => void;
  setCurrentTime: Dispatch<SetStateAction<number>>;
  playbackIntentRef: MutableRefObject<boolean | null>;
  requestPlay: (onRejected?: () => void) => void;
  requestPause: () => void;
  togglePlayback: () => void;
  reportPlaybackStatus: () => void;
}

const GESTURE_DRAG_THRESHOLD_PX = 8;
const TOUCH_GESTURE_DRAG_THRESHOLD_PX = 14;
const PINCH_DRAG_THRESHOLD_PX = 3;
const SUBTITLE_SIZE_MIN = 50;
const SUBTITLE_SIZE_MAX = 150;
const LONG_PRESS_DELAY_MS = 500;
const PREVIEW_SPEED_RATE = 2;

function seekSpanForDuration(duration: number): number {
  if (!Number.isFinite(duration) || duration <= 0) return 0;
  return Math.min(60, Math.max(15, duration * 0.25));
}

function distanceBetween(
  first: StageTouchPoint,
  second: StageTouchPoint,
): number {
  return Math.hypot(second.x - first.x, second.y - first.y);
}

export function usePreviewGestures({
  videoRef,
  containerRef,
  cues,
  currentTime,
  fontSize,
  subtitleTransformControls,
  onTimeUpdate,
  setCurrentTime,
  playbackIntentRef,
  requestPlay,
  requestPause,
  togglePlayback,
  reportPlaybackStatus,
}: UsePreviewGesturesOptions) {
  const gestureRef = useRef<PreviewGesture | null>(null);
  const longPressTimerRef = useRef<number | null>(null);
  const stageTouchPointsRef = useRef<Map<number, StageTouchPoint>>(new Map());
  const stagePinchRef = useRef<StagePinchGesture | null>(null);
  const suppressStageClickRef = useRef(false);
  const [subtitleGestureResetToken, setSubtitleGestureResetToken] = useState(0);
  const [gestureFeedback, setGestureFeedback] =
    useState<GestureFeedback | null>(null);

  const clearLongPressTimer = useCallback(() => {
    if (longPressTimerRef.current !== null) {
      window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  }, []);

  const handlePreviewPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLVideoElement>) => {
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
        wasPlaying:
          playbackIntentRef.current ?? (!video.paused && !video.ended),
        originalPlaybackRate: video.playbackRate,
        dragThreshold:
          event.pointerType === "touch"
            ? TOUCH_GESTURE_DRAG_THRESHOLD_PX
            : GESTURE_DRAG_THRESHOLD_PX,
        mode: "pending",
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
          !gesture ||
          gesture.pointerId !== event.pointerId ||
          gesture.mode !== "pending" ||
          !activeVideo
        ) {
          return;
        }

        gesture.mode = "speed";
        activeVideo.playbackRate = PREVIEW_SPEED_RATE;
        setGestureFeedback({ kind: "speed" });
        try {
          activeVideo.setPointerCapture(event.pointerId);
        } catch {
          // Pointer capture is best-effort on older mobile browsers.
        }

        if (!gesture.wasPlaying) {
          requestPlay(() => {
            activeVideo.playbackRate = gesture.originalPlaybackRate;
            gesture.mode = "cancelled";
            setGestureFeedback(null);
          });
        }
      }, LONG_PRESS_DELAY_MS);
    },
    [clearLongPressTimer, playbackIntentRef, requestPlay, videoRef],
  );

  const handlePreviewPointerMove = useCallback(
    (event: ReactPointerEvent<HTMLVideoElement>) => {
      const gesture = gestureRef.current;
      const video = videoRef.current;
      if (!gesture || !video || gesture.pointerId !== event.pointerId) return;

      const deltaX = event.clientX - gesture.startX;
      const deltaY = event.clientY - gesture.startY;

      if (gesture.mode === "pending") {
        if (Math.hypot(deltaX, deltaY) < gesture.dragThreshold) return;

        clearLongPressTimer();
        if (Math.abs(deltaX) <= Math.abs(deltaY)) {
          gesture.mode = "cancelled";
          return;
        }

        gesture.mode = "seeking";
        requestPause();
        try {
          event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
          // Pointer capture is best-effort on older mobile browsers.
        }
      }

      if (gesture.mode !== "seeking") return;

      event.preventDefault();
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      const seekSpan = seekSpanForDuration(duration);
      if (seekSpan <= 0) return;

      const width = Math.max(
        1,
        event.currentTarget.getBoundingClientRect().width ||
          event.currentTarget.clientWidth,
      );
      const nextTime = clamp(
        gesture.startTime + (deltaX / width) * seekSpan,
        0,
        duration,
      );

      video.currentTime = nextTime;
      setCurrentTime(nextTime);
      onTimeUpdate?.(nextTime);
      setGestureFeedback({
        kind: "seek",
        currentTime: nextTime,
        delta: nextTime - gesture.startTime,
        duration,
      });
    },
    [clearLongPressTimer, onTimeUpdate, requestPause, setCurrentTime, videoRef],
  );

  const finishPreviewGesture = useCallback(
    (event: ReactPointerEvent<HTMLVideoElement>, cancelled = false) => {
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

      if (gesture.mode === "pending" && !cancelled) {
        togglePlayback();
      } else if (
        gesture.mode === "seeking" &&
        gesture.wasPlaying &&
        !cancelled
      ) {
        requestPlay();
      } else if (gesture.mode === "speed") {
        video.playbackRate = gesture.originalPlaybackRate;
        if (!gesture.wasPlaying) {
          requestPause();
          setCurrentTime(video.currentTime);
        }
        reportPlaybackStatus();
      }

      gestureRef.current = null;
      setGestureFeedback(null);
    },
    [
      clearLongPressTimer,
      reportPlaybackStatus,
      requestPause,
      requestPlay,
      setCurrentTime,
      togglePlayback,
      videoRef,
    ],
  );

  useEffect(
    () => () => {
      clearLongPressTimer();
      stagePinchRef.current = null;
      stageTouchPointsRef.current.clear();
      suppressStageClickRef.current = false;
      const gesture = gestureRef.current;
      const video = videoRef.current;
      if (gesture && video) {
        video.playbackRate = gesture.originalPlaybackRate;
      }
      gestureRef.current = null;
    },
    [clearLongPressTimer, videoRef],
  );

  const pauseForSubtitleInteraction = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    requestPause();
    setCurrentTime(video.currentTime);
  }, [requestPause, setCurrentTime, videoRef]);

  const hasActiveTransformCue = useMemo(
    () => findCueIndexAtTime(cues, currentTime) >= 0,
    [cues, currentTime],
  );

  const cancelPreviewGestureForPinch = useCallback(() => {
    clearLongPressTimer();
    const gesture = gestureRef.current;
    const video = videoRef.current;

    if (gesture && video) {
      if (gesture.mode === "speed") {
        video.playbackRate = gesture.originalPlaybackRate;
      } else if (
        gesture.mode === "seeking" &&
        Math.abs(video.currentTime - gesture.startTime) > 0.001
      ) {
        video.currentTime = gesture.startTime;
        setCurrentTime(gesture.startTime);
        onTimeUpdate?.(gesture.startTime);
      }
    }

    gestureRef.current = null;
    setGestureFeedback(null);
  }, [clearLongPressTimer, onTimeUpdate, setCurrentTime, videoRef]);

  const finishStagePinch = useCallback(
    (cancelled: boolean) => {
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
    },
    [containerRef],
  );

  const handleStagePointerDownCapture = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.pointerType !== "touch") return;

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
        startSize: fontSize,
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
    },
    [
      cancelPreviewGestureForPinch,
      fontSize,
      hasActiveTransformCue,
      pauseForSubtitleInteraction,
      subtitleTransformControls,
    ],
  );

  const handleStagePointerMoveCapture = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (
        event.pointerType === "touch" &&
        stageTouchPointsRef.current.has(event.pointerId)
      ) {
        stageTouchPointsRef.current.set(event.pointerId, {
          x: event.clientX,
          y: event.clientY,
        });
      }

      const pinch = stagePinchRef.current;
      if (
        !pinch ||
        !subtitleTransformControls ||
        !pinch.pointerIds.includes(event.pointerId)
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
        !pinch.moved &&
        Math.abs(distance - pinch.startDistance) < PINCH_DRAG_THRESHOLD_PX
      ) {
        return;
      }

      pinch.moved = true;
      subtitleTransformControls.onSizeChange(
        Math.round(
          clamp(
            pinch.startSize * (distance / pinch.startDistance),
            SUBTITLE_SIZE_MIN,
            SUBTITLE_SIZE_MAX,
          ),
        ),
      );
    },
    [subtitleTransformControls],
  );

  const finishStagePointer = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>, cancelled: boolean) => {
      if (event.pointerType !== "touch") return;

      const pinch = stagePinchRef.current;
      if (pinch?.pointerIds.includes(event.pointerId)) {
        event.preventDefault();
        event.stopPropagation();
        finishStagePinch(cancelled);
        return;
      }

      stageTouchPointsRef.current.delete(event.pointerId);
    },
    [finishStagePinch],
  );

  const handleStageLostPointerCapture = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      // Transferring capture from the video or subtitle child to the stage
      // legitimately emits a bubbling lostpointercapture on that child.
      // Only loss of capture owned by the stage interrupts the shared pinch.
      if (event.target !== event.currentTarget) return;
      if (stagePinchRef.current?.pointerIds.includes(event.pointerId)) {
        finishStagePinch(true);
        return;
      }
      stageTouchPointsRef.current.delete(event.pointerId);
    },
    [finishStagePinch],
  );

  const handleStageClickCapture = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (!suppressStageClickRef.current) return;
      event.preventDefault();
      event.stopPropagation();
      suppressStageClickRef.current = false;
    },
    [],
  );

  useEffect(() => {
    const interruptGestures = () => {
      if (stagePinchRef.current) {
        finishStagePinch(true);
      } else {
        stageTouchPointsRef.current.clear();
      }
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") interruptGestures();
    };

    window.addEventListener("blur", interruptGestures);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("blur", interruptGestures);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [finishStagePinch]);

  return {
    gestureFeedback,
    subtitleGestureResetToken,
    pauseForSubtitleInteraction,
    hasActiveTransformCue,
    handlePreviewPointerDown,
    handlePreviewPointerMove,
    finishPreviewGesture,
    handleStagePointerDownCapture,
    handleStagePointerMoveCapture,
    finishStagePointer,
    handleStageLostPointerCapture,
    handleStageClickCapture,
  };
}
