import React from "react";
import type { TranscriptionCue, TranscriptionWordTiming } from "@/lib/api";
import { normalizeSubtitleText } from "@/lib/subtitleUtils";
import { InlineSubtitleEditor } from "./InlineSubtitleEditor";
import { SubtitleOverlayFrame } from "./SubtitleOverlayFrame";
import type {
  SubtitleOverlayEditorState,
  SubtitleOverlaySettings,
  SubtitleTransformControls,
} from "./SubtitleOverlayTypes";
import type { useSubtitleTransformGestures } from "./useSubtitleTransformGestures";

type TransformGestureResult = ReturnType<typeof useSubtitleTransformGestures>;
type CueLine = TranscriptionWordTiming[];

type ActiveSubtitleLayout = {
  activeCue?: TranscriptionCue;
  lines: CueLine[];
  words: TranscriptionWordTiming[];
  lineOffsets: number[];
  activeWordIndex: number;
};

type SubtitleOverlayPresentationProps = {
  layout: ActiveSubtitleLayout;
  settings: SubtitleOverlaySettings;
  videoWidth: number;
  videoHeight: number;
  inlineEditor?: SubtitleOverlayEditorState;
  transformControls?: SubtitleTransformControls;
  positionStyle: React.CSSProperties;
  textStyle: React.CSSProperties;
  overlayRef: TransformGestureResult[0];
  transformHandlers: TransformGestureResult[1];
};

function SingleWordSubtitle({
  word,
  color,
}: {
  word: TranscriptionWordTiming;
  color: string;
}) {
  return (
    <span
      data-testid="subtitle-line"
      className="block whitespace-nowrap"
      style={{ color }}
    >
      {normalizeSubtitleText(String(word.text).trim())}
    </span>
  );
}

function StaticSubtitleLines({
  cue,
  lines,
  color,
}: {
  cue: TranscriptionCue;
  lines: CueLine[];
  color: string;
}) {
  return (
    <span className="block" style={{ color }}>
      {lines.map((line, lineIndex) => (
        <span
          data-testid="subtitle-line"
          data-line-index={lineIndex}
          className="block whitespace-nowrap"
          key={`${cue.start}-static-${lineIndex}`}
        >
          {line.map((word) => word.text).join(" ")}
        </span>
      ))}
    </span>
  );
}

function KaraokeWord({
  word,
  wordIndex,
  wordIndexWithinLine,
  activeWordIndex,
  color,
}: {
  word: TranscriptionWordTiming;
  wordIndex: number;
  wordIndexWithinLine: number;
  activeWordIndex: number;
  color: string;
}) {
  const isActive = wordIndex === activeWordIndex;
  return (
    <React.Fragment key={`${word.start}-${wordIndex}`}>
      {wordIndexWithinLine > 0 ? " " : null}
      <span
        data-testid="subtitle-word"
        data-active={isActive ? "true" : "false"}
        className="transition-[color,text-shadow] duration-75 ease-linear"
        style={{ color: isActive ? color : "rgba(255,255,255,0.9)" }}
      >
        {word.text}
      </span>
    </React.Fragment>
  );
}

function KaraokeSubtitleLines({
  cue,
  lines,
  lineOffsets,
  activeWordIndex,
  color,
}: {
  cue: TranscriptionCue;
  lines: CueLine[];
  lineOffsets: number[];
  activeWordIndex: number;
  color: string;
}) {
  return lines.map((line, lineIndex) => (
    <span
      data-testid="subtitle-line"
      data-line-index={lineIndex}
      className="block whitespace-nowrap"
      key={`${cue.start}-karaoke-${lineIndex}`}
    >
      {line.map((word, wordIndexWithinLine) => (
        <KaraokeWord
          key={`${word.start}-${wordIndexWithinLine}`}
          word={word}
          wordIndex={lineOffsets[lineIndex] + wordIndexWithinLine}
          wordIndexWithinLine={wordIndexWithinLine}
          activeWordIndex={activeWordIndex}
          color={color}
        />
      ))}
    </span>
  ));
}

function SubtitleCueContent({
  layout,
  settings,
}: {
  layout: ActiveSubtitleLayout & { activeCue: TranscriptionCue };
  settings: SubtitleOverlaySettings;
}) {
  if (settings.maxLines === 0 && layout.words.length > 0) {
    const currentWord = layout.words[layout.activeWordIndex];
    return currentWord ? (
      <SingleWordSubtitle word={currentWord} color={settings.color} />
    ) : null;
  }
  const staticMode = !settings.karaoke || !layout.activeCue.words?.length;
  if (staticMode) {
    return (
      <StaticSubtitleLines
        cue={layout.activeCue}
        lines={layout.lines}
        color={settings.color}
      />
    );
  }
  return (
    <KaraokeSubtitleLines
      cue={layout.activeCue}
      lines={layout.lines}
      lineOffsets={layout.lineOffsets}
      activeWordIndex={layout.activeWordIndex}
      color={settings.color}
    />
  );
}

function ActiveSubtitleOverlay({
  layout,
  settings,
  inlineEditor,
  transformControls,
  positionStyle,
  textStyle,
  overlayRef,
  transformHandlers,
}: Omit<SubtitleOverlayPresentationProps, "videoWidth" | "videoHeight"> & {
  layout: ActiveSubtitleLayout & { activeCue: TranscriptionCue };
}) {
  const inlineTrigger = inlineEditor
    ? {
        label: inlineEditor.labels.editAction,
        onBeginEdit: inlineEditor.onBeginEdit,
      }
    : undefined;
  return (
    <SubtitleOverlayFrame
      lineCount={settings.maxLines === 0 ? 1 : layout.lines.length}
      position={settings.position}
      fontSize={settings.fontSize}
      positionStyle={positionStyle}
      textStyle={textStyle}
      inlineTrigger={inlineTrigger}
      transformControls={transformControls}
      overlayRef={overlayRef}
      handlers={transformHandlers}
    >
      <SubtitleCueContent layout={layout} settings={settings} />
    </SubtitleOverlayFrame>
  );
}

export function SubtitleOverlayPresentation({
  layout,
  settings,
  videoWidth,
  videoHeight,
  inlineEditor,
  transformControls,
  positionStyle,
  textStyle,
  overlayRef,
  transformHandlers,
}: SubtitleOverlayPresentationProps) {
  if (!layout.activeCue) return null;
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
  return (
    <ActiveSubtitleOverlay
      layout={{ ...layout, activeCue: layout.activeCue }}
      settings={settings}
      inlineEditor={inlineEditor}
      transformControls={transformControls}
      positionStyle={positionStyle}
      textStyle={textStyle}
      overlayRef={overlayRef}
      transformHandlers={transformHandlers}
    />
  );
}
