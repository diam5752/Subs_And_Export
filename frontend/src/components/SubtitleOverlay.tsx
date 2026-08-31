import React, { useMemo, memo } from "react";
import { TranscriptionCue } from "../lib/api";
import {
  findCueIndexAtTime,
  getSubtitlePositionStyle,
  layoutCueLines,
} from "../lib/subtitleUtils";
import { SubtitleOverlayPresentation } from "./SubtitleOverlayPresentation";
import type {
  SubtitleOverlayEditorState,
  SubtitleOverlaySettings,
  SubtitleTransformControls,
} from "./SubtitleOverlayTypes";
import { useSubtitleTransformGestures } from "./useSubtitleTransformGestures";

export type {
  SubtitlePositionScope,
  SubtitleTransformControls,
} from "./SubtitleOverlayTypes";

export type Cue = TranscriptionCue & {
  /** Index in the persisted transcript when this preview cue was resegmented. */
  sourceCueIndex?: number;
};

interface SubtitleOverlayProps {
  currentTime: number;
  cues: Cue[];
  settings: SubtitleOverlaySettings;
  videoWidth?: number;
  videoHeight?: number;
  inlineEditor?: SubtitleOverlayEditorState;
  transformControls?: SubtitleTransformControls;
  gestureResetToken?: number;
}

function subtitleTextStyle(
  videoWidth: number,
  fontSize: number,
  shadowStrength: number,
): React.CSSProperties {
  const baseSize = videoWidth * (62 / 1080);
  const currentSize = baseSize * (fontSize / 100);
  const shadowPx = shadowStrength * (videoWidth / 1000);
  return {
    fontSize: `${currentSize}px`,
    WebkitTextStroke: `${shadowPx}px rgba(0,0,0,0.8)`,
    textShadow: `${shadowPx}px ${shadowPx}px 0 rgba(0,0,0,0.8)`,
  };
}

function useActiveSubtitleLayout(
  cues: Cue[],
  currentTime: number,
  maxLines: number,
  fontSize: number,
) {
  const activeCueIndex = useMemo(
    () => findCueIndexAtTime(cues, currentTime),
    [currentTime, cues],
  );
  const activeCue = activeCueIndex >= 0 ? cues[activeCueIndex] : undefined;
  const lines = useMemo(
    () => (activeCue ? layoutCueLines(activeCue, maxLines, fontSize) : []),
    [activeCue, fontSize, maxLines],
  );
  const words = useMemo(() => lines.flat(), [lines]);
  const lineOffsets = useMemo(
    () =>
      lines.map((_, lineIndex) =>
        lines
          .slice(0, lineIndex)
          .reduce((count, line) => count + line.length, 0),
      ),
    [lines],
  );
  const activeWordIndex = useMemo(
    () =>
      words.findIndex(
        (word) => currentTime >= word.start && currentTime < word.end,
      ),
    [currentTime, words],
  );
  return {
    activeCue,
    activeCueIndex,
    lines,
    words,
    lineOffsets,
    activeWordIndex,
  };
}

function useOverlayPresentationState(
  activeCue: Cue | undefined,
  activeCueIndex: number,
  settings: SubtitleOverlaySettings,
  videoWidth: number,
) {
  const textStyle = useMemo(
    () =>
      subtitleTextStyle(videoWidth, settings.fontSize, settings.shadowStrength),
    [settings.fontSize, settings.shadowStrength, videoWidth],
  );
  const sourceCueIndex = activeCue?.sourceCueIndex ?? activeCueIndex;
  const hasCustomPosition =
    activeCue?.position !== undefined && activeCue.position !== null;
  const position = hasCustomPosition
    ? (activeCue?.position ?? settings.position)
    : settings.position;
  const positionStyle = useMemo(
    () => getSubtitlePositionStyle(position),
    [position],
  );
  return {
    hasCustomPosition,
    position,
    positionStyle,
    sourceCueIndex,
    textStyle,
  };
}

function SubtitleOverlayContent({
  currentTime,
  cues,
  settings,
  videoWidth = 1080,
  videoHeight = 1920,
  inlineEditor,
  transformControls,
  gestureResetToken = 0,
}: SubtitleOverlayProps) {
  const layout = useActiveSubtitleLayout(
    cues,
    currentTime,
    settings.maxLines,
    settings.fontSize,
  );
  const presentation = useOverlayPresentationState(
    layout.activeCue,
    layout.activeCueIndex,
    settings,
    videoWidth,
  );

  const [overlayRef, transformHandlers] = useSubtitleTransformGestures({
    hasActiveCue: Boolean(layout.activeCue),
    position: presentation.position,
    sourceCueIndex: presentation.sourceCueIndex,
    fontSize: settings.fontSize,
    videoWidth,
    videoHeight,
    transformControls,
    gestureResetToken,
  });
  return (
    <SubtitleOverlayPresentation
      layout={layout}
      settings={{ ...settings, position: presentation.position }}
      videoWidth={videoWidth}
      videoHeight={videoHeight}
      inlineEditor={inlineEditor}
      transformControls={transformControls}
      positionStyle={presentation.positionStyle}
      textStyle={presentation.textStyle}
      overlayRef={overlayRef}
      transformHandlers={transformHandlers}
      hasCustomPosition={presentation.hasCustomPosition}
      sourceCueIndex={presentation.sourceCueIndex}
    />
  );
}

export const SubtitleOverlay = memo(SubtitleOverlayContent);

SubtitleOverlay.displayName = "SubtitleOverlay";
