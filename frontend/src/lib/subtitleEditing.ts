import type { TranscriptionCue as Cue, TranscriptionWordTiming } from "./api";

export const SUBTITLE_POSITION_MIN = 5;
export const SUBTITLE_POSITION_MAX = 95;
const DEFAULT_SUBTITLE_POSITION = 16;

interface SubtitlePositionStyle {
  top: string;
  transform: string;
}

function formatPositionPercent(value: number): string {
  return Number(value.toFixed(3)).toString();
}

/**
 * Map the bottom-to-top slider to a top coordinate while keeping the complete
 * subtitle block inside a 5% safe area at both extremes.
 */
export function getSubtitlePositionStyle(
  position: number,
): SubtitlePositionStyle {
  const numericPosition = Number.isFinite(position)
    ? position
    : DEFAULT_SUBTITLE_POSITION;
  const clampedPosition = Math.min(
    SUBTITLE_POSITION_MAX,
    Math.max(SUBTITLE_POSITION_MIN, numericPosition),
  );
  const progress =
    (clampedPosition - SUBTITLE_POSITION_MIN) /
    (SUBTITLE_POSITION_MAX - SUBTITLE_POSITION_MIN);
  const anchorFromTop = 100 - clampedPosition;
  const translate = (1 - progress) * 100;

  return {
    top: `${formatPositionPercent(anchorFromTop)}%`,
    transform:
      translate === 0
        ? "translateY(0)"
        : `translateY(-${formatPositionPercent(translate)}%)`,
  };
}

/**
 * Reconcile edited subtitle text with the cue's existing word timings.
 * Existing timing boundaries are preserved when possible; added words split
 * the original intervals and removed words merge adjacent intervals.
 */
export function updateCueText(cue: Cue, nextText: string): Cue {
  const normalizedText = nextText.normalize("NFC").replace(/\s+/g, " ").trim();
  const tokens = normalizedText.length > 0 ? normalizedText.split(" ") : [];

  if (!tokens.length) {
    return { ...cue, text: "", words: undefined };
  }

  const oldWords =
    cue.words?.filter((word) => word.text.trim().length > 0) ?? [];
  if (!oldWords.length) {
    return { ...cue, text: normalizedText, words: undefined };
  }

  if (tokens.length === oldWords.length) {
    return {
      ...cue,
      text: normalizedText,
      words: oldWords.map((word, index) => ({ ...word, text: tokens[index] })),
    };
  }

  const words =
    tokens.length < oldWords.length
      ? mergeWordTimings(oldWords, tokens)
      : splitWordTimings(oldWords, tokens);
  return { ...cue, text: normalizedText, words };
}

function mergeWordTimings(
  oldWords: TranscriptionWordTiming[],
  tokens: string[],
): TranscriptionWordTiming[] {
  const base = Math.floor(oldWords.length / tokens.length);
  const remainder = oldWords.length % tokens.length;
  let cursor = 0;
  return tokens.map((text, index) => {
    const size = base + (index < remainder ? 1 : 0);
    const group = oldWords.slice(cursor, cursor + size);
    cursor += size;
    return {
      start: group[0].start,
      end: group[group.length - 1].end,
      text,
    };
  });
}

function splitWordTimings(
  oldWords: TranscriptionWordTiming[],
  tokens: string[],
): TranscriptionWordTiming[] {
  const base = Math.floor(tokens.length / oldWords.length);
  const remainder = tokens.length % oldWords.length;
  const newWords: TranscriptionWordTiming[] = [];
  let tokenCursor = 0;

  for (let index = 0; index < oldWords.length; index += 1) {
    const segments = base + (index < remainder ? 1 : 0);
    const wordStart = oldWords[index].start;
    const wordEnd = oldWords[index].end;
    const segmentDuration =
      Math.max(0, wordEnd - wordStart) / Math.max(1, segments);

    for (let segment = 0; segment < segments; segment += 1) {
      const start = wordStart + segmentDuration * segment;
      const end =
        segment === segments - 1
          ? wordEnd
          : wordStart + segmentDuration * (segment + 1);
      newWords.push({ start, end, text: tokens[tokenCursor] });
      tokenCursor += 1;
    }
  }

  return newWords;
}
