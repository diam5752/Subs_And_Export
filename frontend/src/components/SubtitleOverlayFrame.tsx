import React from "react";
import {
  SUBTITLE_POSITION_MAX,
  SUBTITLE_POSITION_MIN,
} from "@/lib/subtitleUtils";
import type { SubtitleTransformControls } from "./SubtitleOverlayTypes";
import {
  SUBTITLE_SIZE_MAX,
  SUBTITLE_SIZE_MIN,
  type useSubtitleTransformGestures,
} from "./useSubtitleTransformGestures";

type TransformGestureResult = ReturnType<typeof useSubtitleTransformGestures>;
type TransformHandlers = TransformGestureResult[1];

type InlineSubtitleTrigger = {
  label: string;
  onBeginEdit: () => void;
};

type SubtitleOverlayFrameProps = {
  children: React.ReactNode;
  lineCount: number;
  position: number;
  fontSize: number;
  positionStyle: React.CSSProperties;
  textStyle: React.CSSProperties;
  inlineTrigger?: InlineSubtitleTrigger;
  transformControls?: SubtitleTransformControls;
  hasCustomPosition: boolean;
  sourceCueIndex: number;
  overlayRef: TransformGestureResult[0];
  handlers: TransformHandlers;
};

function overlayClassName(
  hasInlineTrigger: boolean,
  hasTransformControls: boolean,
): string {
  const pointerClass =
    hasInlineTrigger || hasTransformControls
      ? "pointer-events-auto"
      : "pointer-events-none";
  const transformClass = hasTransformControls
    ? "group/subtitle touch-none select-none cursor-grab rounded-lg outline outline-1 outline-transparent transition-[outline-color] hover:outline-cyan-400/80 active:cursor-grabbing focus-within:outline-cyan-400/80"
    : "";
  return `absolute left-[7.4%] right-[7.4%] z-20 text-center ${pointerClass} ${transformClass}`;
}

function PositionHandle({
  position,
  controls,
  handlers,
  hasCustomPosition,
}: {
  position: number;
  controls: SubtitleTransformControls;
  handlers: TransformHandlers;
  hasCustomPosition: boolean;
}) {
  return (
    <button
      type="button"
      role="slider"
      data-testid="subtitle-drag-handle"
      aria-label={controls.labels.move}
      aria-orientation="vertical"
      aria-valuemin={SUBTITLE_POSITION_MIN}
      aria-valuemax={SUBTITLE_POSITION_MAX}
      aria-valuenow={position}
      aria-valuetext={`${position}% · ${
        hasCustomPosition
          ? (controls.labels.customPosition ?? "custom position")
          : (controls.labels.sharedPosition ?? "shared position")
      }`}
      title={controls.labels.move}
      onPointerDown={handlers.handlePositionHandlePointerDown}
      onKeyDown={handlers.handlePositionKeyDown}
      className="subtitle-desktop-transform-handle absolute left-0 top-1/2 grid h-8 w-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-cyan-300/80 bg-black/85 text-sm font-black text-cyan-200 shadow-[0_5px_18px_rgba(0,0,0,0.55)] backdrop-blur-sm transition-transform hover:scale-110 focus-visible:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
    >
      <span aria-hidden="true">↕</span>
    </button>
  );
}

function SizeHandle({
  fontSize,
  controls,
  handlers,
}: {
  fontSize: number;
  controls: SubtitleTransformControls;
  handlers: TransformHandlers;
}) {
  return (
    <button
      type="button"
      role="slider"
      data-testid="subtitle-resize-handle"
      data-subtitle-resize-handle
      aria-label={controls.labels.resize}
      aria-orientation="horizontal"
      aria-valuemin={SUBTITLE_SIZE_MIN}
      aria-valuemax={SUBTITLE_SIZE_MAX}
      aria-valuenow={fontSize}
      aria-valuetext={`${fontSize}%`}
      title={controls.labels.resize}
      onPointerDown={handlers.handleResizePointerDown}
      onKeyDown={handlers.handleSizeKeyDown}
      className="subtitle-desktop-transform-handle absolute bottom-0 right-0 grid h-8 w-8 translate-x-1/2 translate-y-1/2 place-items-center rounded-full border border-cyan-300/80 bg-black/85 text-sm font-black text-cyan-200 shadow-[0_5px_18px_rgba(0,0,0,0.55)] backdrop-blur-sm transition-transform hover:scale-110 focus-visible:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
    >
      <span aria-hidden="true">↘</span>
    </button>
  );
}

function TransformHandles({
  position,
  fontSize,
  controls,
  handlers,
  hasCustomPosition,
}: {
  position: number;
  fontSize: number;
  controls: SubtitleTransformControls;
  handlers: TransformHandlers;
  hasCustomPosition: boolean;
}) {
  return (
    <>
      <PositionHandle
        position={position}
        controls={controls}
        handlers={handlers}
        hasCustomPosition={hasCustomPosition}
      />
      <SizeHandle fontSize={fontSize} controls={controls} handlers={handlers} />
    </>
  );
}

function SubtitleText({
  children,
  textStyle,
  inlineTrigger,
  transforming,
}: {
  children: React.ReactNode;
  textStyle: React.CSSProperties;
  inlineTrigger?: InlineSubtitleTrigger;
  transforming: boolean;
}) {
  const body = (
    <span className="subtitle-overlay-text block" style={textStyle}>
      {children}
    </span>
  );
  if (!inlineTrigger) return body;
  const cursorClass = transforming
    ? "cursor-grab active:cursor-grabbing"
    : "cursor-text";
  return (
    <button
      type="button"
      data-testid="inline-subtitle-trigger"
      aria-label={inlineTrigger.label}
      onClick={inlineTrigger.onBeginEdit}
      className={`subtitle-inline-trigger relative m-0 inline-block max-w-full rounded-md border-0 bg-transparent p-0 text-inherit outline-none transition-[box-shadow,background-color] hover:bg-black/20 hover:shadow-[0_0_0_2px_rgba(255,255,255,0.72),0_8px_22px_rgba(0,0,0,0.28)] focus-visible:bg-black/20 focus-visible:shadow-[0_0_0_2px_rgba(255,255,255,0.72),0_8px_22px_rgba(0,0,0,0.28)] ${cursorClass}`}
    >
      {body}
    </button>
  );
}

export function SubtitleOverlayFrame({
  children,
  lineCount,
  position,
  fontSize,
  positionStyle,
  textStyle,
  inlineTrigger,
  transformControls,
  hasCustomPosition,
  sourceCueIndex,
  overlayRef,
  handlers,
}: SubtitleOverlayFrameProps) {
  const transformHandlers = transformControls
    ? {
        onPointerDown: handlers.handlePositionPointerDown,
        onPointerMove: handlers.handlePointerMove,
        onPointerUp: handlers.finishTransform,
        onPointerCancel: (event: React.PointerEvent<HTMLDivElement>) =>
          handlers.finishTransform(event, true),
        onLostPointerCapture: handlers.handleLostPointerCapture,
        onClickCapture: handlers.handleClickCapture,
      }
    : {};
  return (
    <div
      ref={overlayRef}
      data-testid="subtitle-overlay"
      data-line-count={lineCount}
      data-position={position}
      data-position-mode={hasCustomPosition ? "custom" : "shared"}
      data-source-cue-index={sourceCueIndex}
      data-font-size={fontSize}
      className={overlayClassName(
        Boolean(inlineTrigger),
        Boolean(transformControls),
      )}
      style={positionStyle}
      {...transformHandlers}
    >
      <SubtitleText
        textStyle={textStyle}
        inlineTrigger={inlineTrigger}
        transforming={Boolean(transformControls)}
      >
        {children}
      </SubtitleText>
      {transformControls && (
        <TransformHandles
          position={position}
          fontSize={fontSize}
          controls={transformControls}
          handlers={handlers}
          hasCustomPosition={hasCustomPosition}
        />
      )}
    </div>
  );
}
