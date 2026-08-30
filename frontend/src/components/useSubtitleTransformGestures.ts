import React, { useCallback, useEffect, useMemo, useRef } from "react";
import {
  SUBTITLE_POSITION_MAX,
  SUBTITLE_POSITION_MIN,
} from "@/lib/subtitleUtils";
import type { SubtitleTransformControls } from "./SubtitleOverlayTypes";

export const SUBTITLE_SIZE_MIN = 50;
export const SUBTITLE_SIZE_MAX = 150;
const POINTER_DRAG_THRESHOLD_PX = 3;
const TOUCH_DRAG_THRESHOLD_PX = 12;

type PointerPoint = { x: number; y: number };

type SinglePointerGesture = {
  mode: "position" | "size";
  pointerId: number;
  startX: number;
  startY: number;
  startPosition: number;
  startSize: number;
  moved: boolean;
};

type PinchGesture = {
  mode: "pinch";
  pointerIds: readonly [number, number];
  startDistance: number;
  startSize: number;
  moved: boolean;
};

type TransformGesture = SinglePointerGesture | PinchGesture;

type GestureRefs = {
  overlay: React.RefObject<HTMLDivElement | null>;
  gesture: React.MutableRefObject<TransformGesture | null>;
  touchPoints: React.MutableRefObject<Map<number, PointerPoint>>;
  suppressClick: React.MutableRefObject<boolean>;
};

function clampAndRound(value: number, min: number, max: number): number {
  return Math.round(Math.min(max, Math.max(min, value)));
}

function distanceBetween(first: PointerPoint, second: PointerPoint): number {
  return Math.hypot(second.x - first.x, second.y - first.y);
}

function capturePointer(
  element: HTMLDivElement | null,
  pointerId: number,
): void {
  try {
    element?.setPointerCapture?.(pointerId);
  } catch {
    // Pointer capture is best-effort on older mobile browsers.
  }
}

function releasePointer(
  element: HTMLDivElement | null,
  pointerId: number,
): void {
  try {
    if (element?.hasPointerCapture?.(pointerId)) {
      element.releasePointerCapture(pointerId);
    }
  } catch {
    // Capture can already be gone after a browser interruption.
  }
}

function rememberTouchPoint(
  event: React.PointerEvent<HTMLElement>,
  points: Map<number, PointerPoint>,
): void {
  if (event.pointerType !== "touch") return;
  points.set(event.pointerId, { x: event.clientX, y: event.clientY });
}

function tryBeginPinch(
  event: React.PointerEvent<HTMLElement>,
  mode: SinglePointerGesture["mode"],
  startSize: number,
  refs: GestureRefs,
): boolean {
  if (event.pointerType !== "touch" || mode !== "position") return false;
  if (refs.touchPoints.current.size !== 2) return false;
  const [first, second] = Array.from(refs.touchPoints.current.entries());
  const gesture: PinchGesture = {
    mode: "pinch",
    pointerIds: [first[0], second[0]],
    startDistance: Math.max(1, distanceBetween(first[1], second[1])),
    startSize,
    moved: false,
  };
  refs.gesture.current = gesture;
  refs.suppressClick.current = true;
  event.preventDefault();
  gesture.pointerIds.forEach((pointerId) => {
    capturePointer(refs.overlay.current, pointerId);
  });
  return true;
}

function movePinchGesture(
  event: React.PointerEvent<HTMLDivElement>,
  gesture: PinchGesture,
  points: Map<number, PointerPoint>,
  suppressClick: React.MutableRefObject<boolean>,
  controls: SubtitleTransformControls,
): void {
  if (!gesture.pointerIds.includes(event.pointerId)) return;
  const first = points.get(gesture.pointerIds[0]);
  const second = points.get(gesture.pointerIds[1]);
  if (!first || !second) return;
  const distance = distanceBetween(first, second);
  const belowThreshold =
    Math.abs(distance - gesture.startDistance) < POINTER_DRAG_THRESHOLD_PX;
  if (!gesture.moved && belowThreshold) return;
  event.preventDefault();
  gesture.moved = true;
  suppressClick.current = true;
  controls.onSizeChange(
    clampAndRound(
      gesture.startSize * (distance / gesture.startDistance),
      SUBTITLE_SIZE_MIN,
      SUBTITLE_SIZE_MAX,
    ),
  );
}

function moveSinglePointerGesture(
  event: React.PointerEvent<HTMLDivElement>,
  gesture: SinglePointerGesture,
  refs: GestureRefs,
  controls: SubtitleTransformControls,
  videoWidth: number,
  videoHeight: number,
): void {
  if (gesture.pointerId !== event.pointerId) return;
  const deltaX = event.clientX - gesture.startX;
  const deltaY = event.clientY - gesture.startY;
  const dragThreshold =
    event.pointerType === "touch"
      ? TOUCH_DRAG_THRESHOLD_PX
      : POINTER_DRAG_THRESHOLD_PX;
  if (!gesture.moved && Math.hypot(deltaX, deltaY) < dragThreshold) return;
  event.preventDefault();
  gesture.moved = true;
  refs.suppressClick.current = true;
  capturePointer(refs.overlay.current, event.pointerId);
  if (gesture.mode === "position") {
    const positionDelta = -(deltaY / Math.max(1, videoHeight)) * 100;
    controls.onPositionChange(
      clampAndRound(
        gesture.startPosition + positionDelta,
        SUBTITLE_POSITION_MIN,
        SUBTITLE_POSITION_MAX,
      ),
    );
    return;
  }
  const diagonalDelta = (deltaX + deltaY) / 2;
  const sizeDelta = (diagonalDelta / Math.max(1, videoWidth)) * 100;
  controls.onSizeChange(
    clampAndRound(
      gesture.startSize + sizeDelta,
      SUBTITLE_SIZE_MIN,
      SUBTITLE_SIZE_MAX,
    ),
  );
}

function finishPinchGesture(
  event: React.PointerEvent<HTMLDivElement>,
  gesture: PinchGesture,
  cancelled: boolean,
  refs: GestureRefs,
): void {
  if (!gesture.pointerIds.includes(event.pointerId)) return;
  refs.gesture.current = null;
  refs.touchPoints.current.clear();
  refs.suppressClick.current = !cancelled;
  gesture.pointerIds.forEach((pointerId) => {
    releasePointer(refs.overlay.current, pointerId);
  });
}

function finishSinglePointerGesture(
  event: React.PointerEvent<HTMLDivElement>,
  gesture: SinglePointerGesture,
  cancelled: boolean,
  refs: GestureRefs,
): void {
  if (gesture.pointerId !== event.pointerId) return;
  refs.gesture.current = null;
  releasePointer(refs.overlay.current, event.pointerId);
  if (cancelled || !gesture.moved) refs.suppressClick.current = false;
}

function nextKeyboardValue(
  key: string,
  currentValue: number,
  step: number,
  min: number,
  max: number,
): number | null {
  if (key === "ArrowUp" || key === "ArrowRight") return currentValue + step;
  if (key === "ArrowDown" || key === "ArrowLeft") return currentValue - step;
  if (key === "Home") return min;
  if (key === "End") return max;
  return null;
}

export function useSubtitleTransformGestures({
  hasActiveCue,
  position,
  fontSize,
  videoWidth,
  videoHeight,
  transformControls,
  gestureResetToken,
}: {
  hasActiveCue: boolean;
  position: number;
  fontSize: number;
  videoWidth: number;
  videoHeight: number;
  transformControls?: SubtitleTransformControls;
  gestureResetToken: number;
}) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const gestureRef = useRef<TransformGesture | null>(null);
  const activeTouchPointsRef = useRef<Map<number, PointerPoint>>(new Map());
  const suppressClickRef = useRef(false);
  const refs: GestureRefs = useMemo(
    () => ({
      overlay: overlayRef,
      gesture: gestureRef,
      touchPoints: activeTouchPointsRef,
      suppressClick: suppressClickRef,
    }),
    [],
  );

  const resetTransformGesture = useCallback(() => {
    const pointerIds = new Set(activeTouchPointsRef.current.keys());
    const gesture = gestureRef.current;
    if (gesture?.mode === "pinch") {
      gesture.pointerIds.forEach((pointerId) => pointerIds.add(pointerId));
    } else if (gesture) {
      pointerIds.add(gesture.pointerId);
    }
    gestureRef.current = null;
    activeTouchPointsRef.current.clear();
    suppressClickRef.current = false;
    pointerIds.forEach((pointerId) =>
      releasePointer(overlayRef.current, pointerId),
    );
  }, []);

  useEffect(() => {
    if (!hasActiveCue) resetTransformGesture();
  }, [hasActiveCue, resetTransformGesture]);
  useEffect(
    () => resetTransformGesture(),
    [gestureResetToken, resetTransformGesture],
  );
  useEffect(() => resetTransformGesture, [resetTransformGesture]);

  const beginTransform = useCallback(
    (
      event: React.PointerEvent<HTMLElement>,
      mode: SinglePointerGesture["mode"],
    ) => {
      if (!transformControls) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      rememberTouchPoint(event, activeTouchPointsRef.current);
      if (tryBeginPinch(event, mode, fontSize, refs)) return;
      if (gestureRef.current) return;
      suppressClickRef.current = false;
      gestureRef.current = {
        mode,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        startPosition: position,
        startSize: fontSize,
        moved: false,
      };
      transformControls.onInteractionStart?.();
      if (mode === "size") capturePointer(overlayRef.current, event.pointerId);
    },
    [fontSize, position, refs, transformControls],
  );

  const handlePositionPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const target = event.target as HTMLElement;
      if (target.closest("[data-subtitle-resize-handle]")) return;
      beginTransform(event, "position");
    },
    [beginTransform],
  );

  const handlePositionHandlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      beginTransform(event, "position");
      capturePointer(overlayRef.current, event.pointerId);
    },
    [beginTransform],
  );

  const handleResizePointerDown = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
      beginTransform(event, "size");
    },
    [beginTransform],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (activeTouchPointsRef.current.has(event.pointerId)) {
        rememberTouchPoint(event, activeTouchPointsRef.current);
      }
      const gesture = gestureRef.current;
      if (!gesture || !transformControls) return;
      if (gesture.mode === "pinch") {
        movePinchGesture(
          event,
          gesture,
          activeTouchPointsRef.current,
          suppressClickRef,
          transformControls,
        );
        return;
      }
      moveSinglePointerGesture(
        event,
        gesture,
        refs,
        transformControls,
        videoWidth,
        videoHeight,
      );
    },
    [refs, transformControls, videoHeight, videoWidth],
  );

  const finishTransform = useCallback(
    (event: React.PointerEvent<HTMLDivElement>, cancelled = false) => {
      if (event.pointerType === "touch") {
        activeTouchPointsRef.current.delete(event.pointerId);
      }
      const gesture = gestureRef.current;
      if (!gesture) return;
      if (gesture.mode === "pinch") {
        finishPinchGesture(event, gesture, cancelled, refs);
        return;
      }
      finishSinglePointerGesture(event, gesture, cancelled, refs);
    },
    [refs],
  );

  const handleLostPointerCapture = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const gesture = gestureRef.current;
      if (!gesture) {
        activeTouchPointsRef.current.delete(event.pointerId);
        return;
      }
      const ownsPointer =
        gesture.mode === "pinch"
          ? gesture.pointerIds.includes(event.pointerId)
          : gesture.pointerId === event.pointerId;
      if (ownsPointer) resetTransformGesture();
    },
    [resetTransformGesture],
  );

  const handleClickCapture = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!suppressClickRef.current) return;
      event.preventDefault();
      event.stopPropagation();
      suppressClickRef.current = false;
    },
    [],
  );

  const handlePositionKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (!transformControls) return;
      const nextPosition = nextKeyboardValue(
        event.key,
        position,
        event.shiftKey ? 5 : 1,
        SUBTITLE_POSITION_MIN,
        SUBTITLE_POSITION_MAX,
      );
      if (nextPosition === null) return;
      event.preventDefault();
      event.stopPropagation();
      transformControls.onInteractionStart?.();
      transformControls.onPositionChange(
        clampAndRound(
          nextPosition,
          SUBTITLE_POSITION_MIN,
          SUBTITLE_POSITION_MAX,
        ),
      );
    },
    [position, transformControls],
  );

  const handleSizeKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (!transformControls) return;
      const nextSize = nextKeyboardValue(
        event.key,
        fontSize,
        event.shiftKey ? 10 : 5,
        SUBTITLE_SIZE_MIN,
        SUBTITLE_SIZE_MAX,
      );
      if (nextSize === null) return;
      event.preventDefault();
      event.stopPropagation();
      transformControls.onInteractionStart?.();
      transformControls.onSizeChange(
        clampAndRound(nextSize, SUBTITLE_SIZE_MIN, SUBTITLE_SIZE_MAX),
      );
    },
    [fontSize, transformControls],
  );

  const handlers = useMemo(
    () => ({
      finishTransform,
      handleClickCapture,
      handleLostPointerCapture,
      handlePointerMove,
      handlePositionHandlePointerDown,
      handlePositionKeyDown,
      handlePositionPointerDown,
      handleResizePointerDown,
      handleSizeKeyDown,
    }),
    [
      finishTransform,
      handleClickCapture,
      handleLostPointerCapture,
      handlePointerMove,
      handlePositionHandlePointerDown,
      handlePositionKeyDown,
      handlePositionPointerDown,
      handleResizePointerDown,
      handleSizeKeyDown,
    ],
  );
  return [overlayRef, handlers] as const;
}
