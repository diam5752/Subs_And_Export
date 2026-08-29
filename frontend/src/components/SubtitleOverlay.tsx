import React, { useCallback, useEffect, useMemo, useRef, memo } from 'react';
import { TranscriptionCue } from '../lib/api';
import {
    findCueAtTime,
    getSubtitlePositionStyle,
    layoutCueLines,
    normalizeSubtitleText,
    SUBTITLE_POSITION_MAX,
    SUBTITLE_POSITION_MIN,
} from '../lib/subtitleUtils';
import { InlineSubtitleEditor, type InlineSubtitleEditorLabels } from './InlineSubtitleEditor';

export type Cue = TranscriptionCue;

const SUBTITLE_SIZE_MIN = 50;
const SUBTITLE_SIZE_MAX = 150;
const POINTER_DRAG_THRESHOLD_PX = 3;
const TOUCH_DRAG_THRESHOLD_PX = 12;

interface SubtitleOverlayEditorState {
    cueIndex: number;
    isEditing: boolean;
    draftText: string;
    isSaving: boolean;
    error?: string | null;
    autoFocus?: boolean;
    labels: InlineSubtitleEditorLabels & { editAction: string };
    onBeginEdit: () => void;
    onChange: (text: string) => void;
    onSave: () => void;
    onCancel: () => void;
}

export interface SubtitleTransformControls {
    labels: {
        move: string;
        resize: string;
    };
    onPositionChange: (position: number) => void;
    onSizeChange: (size: number) => void;
    onInteractionStart?: () => void;
}

interface SubtitleOverlayProps {
    currentTime: number;
    cues: Cue[];
    settings: {
        position: number; // 5-95 progression from the safe bottom to safe top edge
        color: string;
        fontSize: number; // 50-150%
        karaoke: boolean;
        maxLines: number;
        shadowStrength: number;
    };
    videoWidth?: number;
    videoHeight?: number;
    inlineEditor?: SubtitleOverlayEditorState;
    transformControls?: SubtitleTransformControls;
    gestureResetToken?: number;
}

type PointerPoint = {
    x: number;
    y: number;
};

type SinglePointerGesture = {
    mode: 'position' | 'size';
    pointerId: number;
    startX: number;
    startY: number;
    startPosition: number;
    startSize: number;
    moved: boolean;
};

type PinchGesture = {
    mode: 'pinch';
    pointerIds: readonly [number, number];
    startDistance: number;
    startSize: number;
    moved: boolean;
};

type TransformGesture = SinglePointerGesture | PinchGesture;

function clampAndRound(value: number, min: number, max: number): number {
    return Math.round(Math.min(max, Math.max(min, value)));
}

function distanceBetween(first: PointerPoint, second: PointerPoint): number {
    return Math.hypot(second.x - first.x, second.y - first.y);
}

export const SubtitleOverlay = memo<SubtitleOverlayProps>(({
    currentTime,
    cues,
    settings,
    videoWidth = 1080,
    videoHeight = 1920,
    inlineEditor,
    transformControls,
    gestureResetToken = 0,
}) => {
    const overlayRef = useRef<HTMLDivElement>(null);
    const gestureRef = useRef<TransformGesture | null>(null);
    const activeTouchPointsRef = useRef<Map<number, PointerPoint>>(new Map());
    const suppressClickRef = useRef(false);

    // 1. Find active cue
    const activeCue = useMemo(() => {
        return findCueAtTime(cues, currentTime);
    }, [currentTime, cues]);

    const resetTransformGesture = useCallback(() => {
        const pointerIds = new Set(activeTouchPointsRef.current.keys());
        const gesture = gestureRef.current;
        if (gesture?.mode === 'pinch') {
            for (const pointerId of gesture.pointerIds) pointerIds.add(pointerId);
        } else if (gesture) {
            pointerIds.add(gesture.pointerId);
        }

        gestureRef.current = null;
        activeTouchPointsRef.current.clear();
        suppressClickRef.current = false;

        for (const pointerId of pointerIds) {
            try {
                if (overlayRef.current?.hasPointerCapture?.(pointerId)) {
                    overlayRef.current.releasePointerCapture(pointerId);
                }
            } catch {
                // Capture can disappear when WebKit removes or retargets a cue.
            }
        }
    }, []);

    useEffect(() => {
        if (!activeCue) resetTransformGesture();
    }, [activeCue, resetTransformGesture]);

    useEffect(() => {
        resetTransformGesture();
    }, [gestureResetToken, resetTransformGesture]);

    useEffect(() => resetTransformGesture, [resetTransformGesture]);

    const activeCueLines = useMemo(() => {
        if (!activeCue) return [];
        return layoutCueLines(activeCue, settings.maxLines, settings.fontSize);
    }, [activeCue, settings.fontSize, settings.maxLines]);

    const activeCueWords = useMemo(
        () => activeCueLines.flat(),
        [activeCueLines],
    );

    const activeCueLineOffsets = useMemo(
        () => activeCueLines.map((_, lineIndex) => (
            activeCueLines
                .slice(0, lineIndex)
                .reduce((wordCount, line) => wordCount + line.length, 0)
        )),
        [activeCueLines],
    );

    // 2. Base Styles
    // Map settings to CSS
    const textStyle = useMemo<React.CSSProperties>(() => {
        // Backend uses 62px base font size on 1080px width (approx 5.74%)
        const baseSize = videoWidth * (62 / 1080);
        const currentSize = baseSize * (settings.fontSize / 100);

        // Shadow logic (approximate ASS shadow)
        const shadowPx = settings.shadowStrength * (videoWidth / 1000);

        return {
            fontSize: `${currentSize}px`,
            WebkitTextStroke: `${shadowPx}px rgba(0,0,0,0.8)`,
            textShadow: `${shadowPx}px ${shadowPx}px 0 rgba(0,0,0,0.8)`,
        };
    }, [settings.fontSize, settings.shadowStrength, videoWidth]);
    const positionStyle = useMemo(
        () => getSubtitlePositionStyle(settings.position),
        [settings.position],
    );

    const beginTransform = useCallback((
        event: React.PointerEvent<HTMLElement>,
        mode: SinglePointerGesture['mode'],
    ) => {
        if (!transformControls || (event.pointerType === 'mouse' && event.button !== 0)) return;

        if (event.pointerType === 'touch') {
            activeTouchPointsRef.current.set(event.pointerId, {
                x: event.clientX,
                y: event.clientY,
            });

            if (mode === 'position' && activeTouchPointsRef.current.size === 2) {
                const points = Array.from(activeTouchPointsRef.current.entries());
                const first = points[0];
                const second = points[1];

                gestureRef.current = {
                    mode: 'pinch',
                    pointerIds: [first[0], second[0]],
                    startDistance: Math.max(1, distanceBetween(first[1], second[1])),
                    startSize: settings.fontSize,
                    moved: false,
                };
                suppressClickRef.current = true;
                event.preventDefault();
                for (const pointerId of gestureRef.current.pointerIds) {
                    try {
                        overlayRef.current?.setPointerCapture?.(pointerId);
                    } catch {
                        // Pointer capture is best-effort on older mobile browsers.
                    }
                }
                return;
            }
        }

        if (gestureRef.current) return;

        suppressClickRef.current = false;
        gestureRef.current = {
            mode,
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            startPosition: settings.position,
            startSize: settings.fontSize,
            moved: false,
        };
        transformControls.onInteractionStart?.();
        if (mode === 'size') {
            try {
                overlayRef.current?.setPointerCapture?.(event.pointerId);
            } catch {
                // Pointer capture is best-effort on older mobile browsers.
            }
        }
    }, [settings.fontSize, settings.position, transformControls]);

    const handlePositionPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
        const target = event.target as HTMLElement;
        if (target.closest('[data-subtitle-resize-handle]')) return;
        beginTransform(event, 'position');
    }, [beginTransform]);

    const handlePositionHandlePointerDown = useCallback((
        event: React.PointerEvent<HTMLButtonElement>,
    ) => {
        event.stopPropagation();
        beginTransform(event, 'position');
        try {
            // The edge handle can leave the overlay on its first movement.
            // Capture it now without retargeting ordinary subtitle-edit clicks.
            overlayRef.current?.setPointerCapture?.(event.pointerId);
        } catch {
            // Pointer capture is best-effort on older mobile browsers.
        }
    }, [beginTransform]);

    const handleResizePointerDown = useCallback((event: React.PointerEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        beginTransform(event, 'size');
    }, [beginTransform]);

    const handlePointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
        if (event.pointerType === 'touch' && activeTouchPointsRef.current.has(event.pointerId)) {
            activeTouchPointsRef.current.set(event.pointerId, {
                x: event.clientX,
                y: event.clientY,
            });
        }

        const gesture = gestureRef.current;
        if (!gesture || !transformControls) return;

        if (gesture.mode === 'pinch') {
            if (!gesture.pointerIds.includes(event.pointerId)) return;

            const first = activeTouchPointsRef.current.get(gesture.pointerIds[0]);
            const second = activeTouchPointsRef.current.get(gesture.pointerIds[1]);
            if (!first || !second) return;

            const distance = distanceBetween(first, second);
            if (
                !gesture.moved
                && Math.abs(distance - gesture.startDistance) < POINTER_DRAG_THRESHOLD_PX
            ) {
                return;
            }

            event.preventDefault();
            gesture.moved = true;
            suppressClickRef.current = true;
            transformControls.onSizeChange(clampAndRound(
                gesture.startSize * (distance / gesture.startDistance),
                SUBTITLE_SIZE_MIN,
                SUBTITLE_SIZE_MAX,
            ));
            return;
        }

        if (gesture.pointerId !== event.pointerId) return;

        const deltaX = event.clientX - gesture.startX;
        const deltaY = event.clientY - gesture.startY;
        const dragThreshold = event.pointerType === 'touch'
            ? TOUCH_DRAG_THRESHOLD_PX
            : POINTER_DRAG_THRESHOLD_PX;
        if (!gesture.moved && Math.hypot(deltaX, deltaY) < dragThreshold) return;

        event.preventDefault();
        gesture.moved = true;
        suppressClickRef.current = true;
        try {
            overlayRef.current?.setPointerCapture?.(event.pointerId);
        } catch {
            // Pointer capture is best-effort on older mobile browsers.
        }

        if (gesture.mode === 'position') {
            const positionDelta = -(deltaY / Math.max(1, videoHeight)) * 100;
            transformControls.onPositionChange(clampAndRound(
                gesture.startPosition + positionDelta,
                SUBTITLE_POSITION_MIN,
                SUBTITLE_POSITION_MAX,
            ));
            return;
        }

        const diagonalDelta = (deltaX + deltaY) / 2;
        const sizeDelta = (diagonalDelta / Math.max(1, videoWidth)) * 100;
        transformControls.onSizeChange(clampAndRound(
            gesture.startSize + sizeDelta,
            SUBTITLE_SIZE_MIN,
            SUBTITLE_SIZE_MAX,
        ));
    }, [transformControls, videoHeight, videoWidth]);

    const finishTransform = useCallback((
        event: React.PointerEvent<HTMLDivElement>,
        cancelled = false,
    ) => {
        if (event.pointerType === 'touch') {
            activeTouchPointsRef.current.delete(event.pointerId);
        }

        const gesture = gestureRef.current;
        if (!gesture) return;

        if (gesture.mode === 'pinch') {
            if (!gesture.pointerIds.includes(event.pointerId)) return;

            const pointerIds = gesture.pointerIds;
            gestureRef.current = null;
            activeTouchPointsRef.current.clear();
            suppressClickRef.current = !cancelled;
            for (const pointerId of pointerIds) {
                try {
                    if (overlayRef.current?.hasPointerCapture?.(pointerId)) {
                        overlayRef.current.releasePointerCapture(pointerId);
                    }
                } catch {
                    // Capture can already be gone after a browser interruption.
                }
            }
            return;
        }

        if (gesture.pointerId !== event.pointerId) return;

        gestureRef.current = null;
        try {
            if (overlayRef.current?.hasPointerCapture?.(event.pointerId)) {
                overlayRef.current.releasePointerCapture(event.pointerId);
            }
        } catch {
            // Capture can already be gone after a browser interruption.
        }
        if (cancelled || !gesture.moved) {
            suppressClickRef.current = false;
        }
    }, []);

    const handleLostPointerCapture = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
        const gesture = gestureRef.current;
        if (!gesture) {
            activeTouchPointsRef.current.delete(event.pointerId);
            return;
        }

        const ownsPointer = gesture.mode === 'pinch'
            ? gesture.pointerIds.includes(event.pointerId)
            : gesture.pointerId === event.pointerId;
        if (ownsPointer) resetTransformGesture();
    }, [resetTransformGesture]);

    const handleClickCapture = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
        if (!suppressClickRef.current) return;
        event.preventDefault();
        event.stopPropagation();
        suppressClickRef.current = false;
    }, []);

    const handlePositionKeyDown = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
        if (!transformControls) return;

        const step = event.shiftKey ? 5 : 1;
        let nextPosition: number | null = null;
        if (event.key === 'ArrowUp' || event.key === 'ArrowRight') {
            nextPosition = settings.position + step;
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') {
            nextPosition = settings.position - step;
        } else if (event.key === 'Home') {
            nextPosition = SUBTITLE_POSITION_MIN;
        } else if (event.key === 'End') {
            nextPosition = SUBTITLE_POSITION_MAX;
        }
        if (nextPosition === null) return;

        event.preventDefault();
        event.stopPropagation();
        transformControls.onInteractionStart?.();
        transformControls.onPositionChange(clampAndRound(
            nextPosition,
            SUBTITLE_POSITION_MIN,
            SUBTITLE_POSITION_MAX,
        ));
    }, [settings.position, transformControls]);

    const handleSizeKeyDown = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
        if (!transformControls) return;

        const step = event.shiftKey ? 10 : 5;
        let nextSize: number | null = null;
        if (event.key === 'ArrowUp' || event.key === 'ArrowRight') {
            nextSize = settings.fontSize + step;
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') {
            nextSize = settings.fontSize - step;
        } else if (event.key === 'Home') {
            nextSize = SUBTITLE_SIZE_MIN;
        } else if (event.key === 'End') {
            nextSize = SUBTITLE_SIZE_MAX;
        }
        if (nextSize === null) return;

        event.preventDefault();
        event.stopPropagation();
        transformControls.onInteractionStart?.();
        transformControls.onSizeChange(clampAndRound(
            nextSize,
            SUBTITLE_SIZE_MIN,
            SUBTITLE_SIZE_MAX,
        ));
    }, [settings.fontSize, transformControls]);

    // OPTIMIZATION: Calculate active word index separately
    // This allows us to memoize the rendered nodes and avoid re-creating them every frame
    // unless the active word actually changes.
    const activeWordIndex = useMemo(() => {
        return activeCueWords.findIndex(w => currentTime >= w.start && currentTime < w.end);
    }, [activeCueWords, currentTime]);

    // 3. Render Content (Memoized)
    return useMemo(() => {
        if (!activeCue) return null;

        if (inlineEditor?.isEditing) {
            return (
                <InlineSubtitleEditor
                    cueIndex={inlineEditor.cueIndex}
                    draftText={inlineEditor.draftText}
                    isSaving={inlineEditor.isSaving}
                    error={inlineEditor.error}
                    autoFocus={inlineEditor.autoFocus}
                    position={settings.position}
                    videoWidth={videoWidth}
                    videoHeight={videoHeight}
                    labels={inlineEditor.labels}
                    onChange={inlineEditor.onChange}
                    onSave={inlineEditor.onSave}
                    onCancel={inlineEditor.onCancel}
                />
            );
        }

        const renderOverlay = (content: React.ReactNode, lineCount: number) => {
            const body = (
                <span className="subtitle-overlay-text block" style={textStyle}>
                    {content}
                </span>
            );

            return (
                <div
                    ref={overlayRef}
                    data-testid="subtitle-overlay"
                    data-line-count={lineCount}
                    data-position={settings.position}
                    data-font-size={settings.fontSize}
                    className={`absolute left-[7.4%] right-[7.4%] z-20 text-center ${
                        inlineEditor || transformControls ? 'pointer-events-auto' : 'pointer-events-none'
                    } ${
                        transformControls
                            ? 'group/subtitle touch-none select-none cursor-grab rounded-lg outline outline-1 outline-transparent transition-[outline-color] hover:outline-cyan-400/80 active:cursor-grabbing focus-within:outline-cyan-400/80'
                            : ''
                    }`}
                    style={positionStyle}
                    onPointerDown={transformControls ? handlePositionPointerDown : undefined}
                    onPointerMove={transformControls ? handlePointerMove : undefined}
                    onPointerUp={transformControls ? finishTransform : undefined}
                    onPointerCancel={transformControls ? (event) => finishTransform(event, true) : undefined}
                    onLostPointerCapture={transformControls ? handleLostPointerCapture : undefined}
                    onClickCapture={transformControls ? handleClickCapture : undefined}
                >
                    {inlineEditor ? (
                        <button
                            type="button"
                            data-testid="inline-subtitle-trigger"
                            aria-label={inlineEditor.labels.editAction}
                            onClick={inlineEditor.onBeginEdit}
                            className={`subtitle-inline-trigger relative m-0 inline-block max-w-full rounded-md border-0 bg-transparent p-0 text-inherit outline-none transition-[box-shadow,background-color] hover:bg-black/20 hover:shadow-[0_0_0_2px_rgba(255,255,255,0.72),0_8px_22px_rgba(0,0,0,0.28)] focus-visible:bg-black/20 focus-visible:shadow-[0_0_0_2px_rgba(255,255,255,0.72),0_8px_22px_rgba(0,0,0,0.28)] ${
                                transformControls ? 'cursor-grab active:cursor-grabbing' : 'cursor-text'
                            }`}
                        >
                            {body}
                        </button>
                    ) : body}
                    {transformControls && (
                        <>
                            <button
                                type="button"
                                role="slider"
                                data-testid="subtitle-drag-handle"
                                aria-label={transformControls.labels.move}
                                aria-orientation="vertical"
                                aria-valuemin={SUBTITLE_POSITION_MIN}
                                aria-valuemax={SUBTITLE_POSITION_MAX}
                                aria-valuenow={settings.position}
                                aria-valuetext={`${settings.position}%`}
                                title={transformControls.labels.move}
                                onPointerDown={handlePositionHandlePointerDown}
                                onKeyDown={handlePositionKeyDown}
                                className="subtitle-desktop-transform-handle absolute left-0 top-1/2 grid h-8 w-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-cyan-300/80 bg-black/85 text-sm font-black text-cyan-200 shadow-[0_5px_18px_rgba(0,0,0,0.55)] backdrop-blur-sm transition-transform hover:scale-110 focus-visible:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                            >
                                <span aria-hidden="true">↕</span>
                            </button>
                            <button
                                type="button"
                                role="slider"
                                data-testid="subtitle-resize-handle"
                                data-subtitle-resize-handle
                                aria-label={transformControls.labels.resize}
                                aria-orientation="horizontal"
                                aria-valuemin={SUBTITLE_SIZE_MIN}
                                aria-valuemax={SUBTITLE_SIZE_MAX}
                                aria-valuenow={settings.fontSize}
                                aria-valuetext={`${settings.fontSize}%`}
                                title={transformControls.labels.resize}
                                onPointerDown={handleResizePointerDown}
                                onKeyDown={handleSizeKeyDown}
                                className="subtitle-desktop-transform-handle absolute bottom-0 right-0 grid h-8 w-8 translate-x-1/2 translate-y-1/2 place-items-center rounded-full border border-cyan-300/80 bg-black/85 text-sm font-black text-cyan-200 shadow-[0_5px_18px_rgba(0,0,0,0.55)] backdrop-blur-sm transition-transform hover:scale-110 focus-visible:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                            >
                                <span aria-hidden="true">↘</span>
                            </button>
                        </>
                    )}
                </div>
            );
        };

        // Mode A: One Word At A Time (maxLines === 0)
        if (settings.maxLines === 0 && activeCueWords.length > 0) {
            const currentWord = activeWordIndex !== -1 ? activeCueWords[activeWordIndex] : null;

            // If between words in the same cue, maybe show nothing or the last/next?
            // Typically strict sync = show matching. If silence, show nothing.
            if (!currentWord) return null;

            return renderOverlay(
                <span
                    data-testid="subtitle-line"
                    className="block whitespace-nowrap"
                    style={{ color: settings.color }}
                >
                    {normalizeSubtitleText(String(currentWord.text).trim())}
                </span>,
                1,
            );
        }

        // Mode B: Karaoke / Standard Static
        // If Karaoke is OFF or NO Words, just render text in Primary Color
        if (!settings.karaoke || !activeCue.words || activeCue.words.length === 0) {
            return renderOverlay(
                <span className="block" style={{ color: settings.color }}>
                    {activeCueLines.map((line, lineIndex) => (
                        <span
                            data-testid="subtitle-line"
                            data-line-index={lineIndex}
                            className="block whitespace-nowrap"
                            key={`${activeCue.start}-static-${lineIndex}`}
                        >
                            {line.map((word) => word.text).join(' ')}
                        </span>
                    ))}
                </span>,
                activeCueLines.length,
            );
        }

        // Mode C: Karaoke Fill (Highlight active word in sentence)
        const karaokeLines = activeCueLines.map((line, lineIndex) => {
            return (
                <span
                    data-testid="subtitle-line"
                    data-line-index={lineIndex}
                    className="block whitespace-nowrap"
                    key={`${activeCue.start}-karaoke-${lineIndex}`}
                >
                    {line.map((word, wordIndexWithinLine) => {
                        const wordIndex = activeCueLineOffsets[lineIndex] + wordIndexWithinLine;
                        const isActive = wordIndex === activeWordIndex;

                        return (
                            <React.Fragment key={`${word.start}-${wordIndex}`}>
                                {wordIndexWithinLine > 0 ? ' ' : null}
                                <span
                                    data-testid="subtitle-word"
                                    data-active={isActive ? 'true' : 'false'}
                                    className="transition-[color,text-shadow] duration-75 ease-linear"
                                    style={{ color: isActive ? settings.color : 'rgba(255,255,255,0.9)' }}
                                >
                                    {word.text}
                                </span>
                            </React.Fragment>
                        );
                    })}
                </span>
            );
        });

        return renderOverlay(karaokeLines, activeCueLines.length);
    }, [
        activeCue,
        activeCueLineOffsets,
        activeCueLines,
        activeCueWords,
        activeWordIndex,
        settings.maxLines,
        settings.karaoke,
        settings.color,
        settings.fontSize,
        settings.position,
        positionStyle,
        textStyle,
        inlineEditor,
        transformControls,
        finishTransform,
        handleClickCapture,
        handleLostPointerCapture,
        handlePointerMove,
        handlePositionKeyDown,
        handlePositionPointerDown,
        handlePositionHandlePointerDown,
        handleResizePointerDown,
        handleSizeKeyDown,
        videoHeight,
        videoWidth,
    ]);
});

SubtitleOverlay.displayName = 'SubtitleOverlay';
