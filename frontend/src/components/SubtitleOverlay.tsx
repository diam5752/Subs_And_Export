import React, { useMemo, memo } from "react";
import { TranscriptionCue } from "../lib/api";
import {
  findCueAtTime,
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

export type { SubtitleTransformControls } from "./SubtitleOverlayTypes";

export type Cue = TranscriptionCue;

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
  const activeCue = useMemo(
    () => findCueAtTime(cues, currentTime),
    [currentTime, cues],
  );
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
  return { activeCue, lines, words, lineOffsets, activeWordIndex };
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
  const textStyle = useMemo(
    () =>
      subtitleTextStyle(videoWidth, settings.fontSize, settings.shadowStrength),
    [settings.fontSize, settings.shadowStrength, videoWidth],
  );
  const positionStyle = useMemo(
    () => getSubtitlePositionStyle(settings.position),
    [settings.position],
  );

  const [overlayRef, transformHandlers] = useSubtitleTransformGestures({
    hasActiveCue: Boolean(layout.activeCue),
    position: settings.position,
    fontSize: settings.fontSize,
    videoWidth,
    videoHeight,
    transformControls,
    gestureResetToken,
  });
  return (
    <SubtitleOverlayPresentation
      layout={layout}
      settings={settings}
      videoWidth={videoWidth}
      videoHeight={videoHeight}
      inlineEditor={inlineEditor}
      transformControls={transformControls}
      positionStyle={positionStyle}
      textStyle={textStyle}
      overlayRef={overlayRef}
      transformHandlers={transformHandlers}
    />
  );
}

export const SubtitleOverlay = memo(SubtitleOverlayContent);

SubtitleOverlay.displayName = "SubtitleOverlay";
