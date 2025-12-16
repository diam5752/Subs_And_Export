import { TranscriptionCue as Cue, TranscriptionWordTiming } from './api';

// Configuration matching backend config.py
const DEFAULT_SUB_FONT_SIZE = 62;

const MAX_SUB_LINE_CHARS = 28; // Safe characters per line for Greek uppercase

/**
 * Estimate the effective character limit per line based on font size and video width.
 * Mirrored from backend `_effective_max_chars`
 */
function getEffectiveMaxChars(fontSizePercent: number): number {
    // Backend logic:
    // base_font = 62
    // font_scale = base_font / (base_font * (percent/100)) = 1 / (percent/100)
    // Actually backend: font_size parameter IS the scaled size (e.g. 62 * 1.5).
    // Let's replicate the math:

    // config.py:
    // size = subtitle_size (e.g. 100)
    // font_size = round(62 * size / 100)

    const fontSizePx = Math.round(DEFAULT_SUB_FONT_SIZE * (fontSizePercent / 100));

    // effective = max_chars * width_scale * font_scale
    // width_scale = 1 (assuming we normalize to 1080p logic for "chars count")
    // font_scale = 62 / fontSizePx

    const fontScale = DEFAULT_SUB_FONT_SIZE / Math.max(1, fontSizePx);

    // In backend video_processing:
    // width_scale = play_res_x / 1080
    // But character count limit (28) is tuned for 1080p with default font.
    // If we render at actual video width, we should scale max chars?
    // Actually, simple proxy:
    const effective = Math.round(MAX_SUB_LINE_CHARS * fontScale);
    return Math.max(10, Math.min(60, effective));
}

/**
 * Flatten all words from a list of cues into a single timeline.
 */
function expandPhraseTiming(word: TranscriptionWordTiming): TranscriptionWordTiming[] {
    const parts = word.text.split(/\s+/).filter(Boolean);
    if (parts.length <= 1) return [word];

    const totalDuration = word.end - word.start;
    const totalChars = word.text.replace(/\s+/g, '').length;
    const safeTotalChars = totalChars > 0 ? totalChars : parts.length;

    let currentStart = word.start;
    const expanded: TranscriptionWordTiming[] = [];

    for (let i = 0; i < parts.length; i += 1) {
        const part = parts[i];
        const charCount = part.length;
        const fraction = safeTotalChars > 0 ? charCount / safeTotalChars : 1 / parts.length;
        const duration = totalDuration * fraction;

        let end = Math.min(currentStart + duration, word.end);
        if (i === parts.length - 1) end = word.end;

        expanded.push({ start: currentStart, end, text: part });
        currentStart = end;
    }

    return expanded;
}

function interpolateWordsFromCueText(cue: Cue): TranscriptionWordTiming[] {
    const cueWords = cue.text.split(/\s+/).filter(Boolean);
    if (cueWords.length === 0) return [];

    const cueDuration = cue.end - cue.start;
    const totalChars = cue.text.replace(/\s+/g, '').length;
    const safeTotalChars = totalChars > 0 ? totalChars : cueWords.length;

    let currentStart = cue.start;
    const timings: TranscriptionWordTiming[] = [];

    for (let i = 0; i < cueWords.length; i += 1) {
        const word = cueWords[i];
        const wordChars = word.length;
        const fraction = safeTotalChars > 0 ? wordChars / safeTotalChars : 1 / cueWords.length;
        const duration = cueDuration * fraction;

        let end = currentStart + duration;
        if (i === cueWords.length - 1) {
            end = cue.end;
        } else {
            end = Math.min(end, cue.end);
        }

        timings.push({ start: currentStart, end, text: word });
        currentStart = end;
    }

    return timings;
}

function getAllWords(cues: Cue[]): TranscriptionWordTiming[] {
    const words: TranscriptionWordTiming[] = [];

    cues.forEach((cue) => {
        if (cue.words && cue.words.length > 0) {
            cue.words.forEach((word) => {
                words.push(...expandPhraseTiming(word));
            });
            return;
        }

        words.push(...interpolateWordsFromCueText(cue));
    });

    return words.sort((a, b) => a.start - b.start);
}

function chunkTimedWords(
    words: TranscriptionWordTiming[],
    maxChars: number,
    maxLines: number
): TranscriptionWordTiming[][] {
    const chunks: TranscriptionWordTiming[][] = [];
    if (words.length === 0) return chunks;

    let currentChunk: TranscriptionWordTiming[] = [];
    let currentLines = 1;
    let currentLineChars = 0;

    for (const word of words) {
        const text = word.text;
        const wordLen = text.length;
        const space = currentLineChars > 0 ? 1 : 0;

        if (currentLineChars + space + wordLen <= maxChars) {
            currentLineChars += space + wordLen;
        } else {
            const wordLines = wordLen > maxChars ? Math.ceil(wordLen / maxChars) : 1;

            if (currentChunk.length > 0 && currentLines + wordLines > maxLines) {
                chunks.push(currentChunk);
                currentChunk = [];
                currentLines = 1;
                currentLineChars = 0;
                currentLines = wordLines;
            } else {
                if (currentChunk.length > 0) {
                    currentLines += 1;
                } else {
                    currentLines = 1;
                }

                if (wordLen > maxChars) {
                    currentLines += wordLines - 1;
                }
            }

            if (wordLen > maxChars) {
                const remainder = wordLen % maxChars;
                currentLineChars = remainder === 0 ? maxChars : remainder;
            } else {
                currentLineChars = wordLen;
            }
        }

        currentChunk.push(word);
    }

    if (currentChunk.length > 0) chunks.push(currentChunk);
    return chunks;
}

/**
 * Re-segment cues to fit within maxLines constraints.
 * Ports backend `_split_long_cues` logic.
 */
export function resegmentCues(
    originalCues: Cue[],
    maxLines: number,
    fontSizePercent: number
): Cue[] {
    if (!originalCues || originalCues.length === 0) return [];
    if (maxLines === 0) return originalCues; // Handled by SubtitleOverlay specially ("One Word" mode)

    // 1. Get all words
    const allWords = getAllWords(originalCues);
    if (allWords.length === 0) return originalCues;

    const maxCharsPerLine = getEffectiveMaxChars(fontSizePercent);

    const wordChunks = chunkTimedWords(allWords, maxCharsPerLine, maxLines);

    const newCues: Cue[] = wordChunks
        .filter((chunkWords) => chunkWords.length > 0)
        .map((chunkWords) => {
            const first = chunkWords[0];
            const last = chunkWords[chunkWords.length - 1];
            return {
                start: first.start,
                end: last.end,
                text: chunkWords.map((w) => w.text).join(' '),
                words: chunkWords,
            };
        });

    // 3. Gap Filling (Optional Polish)
    // Improve smoothness by extending end times to bridge small gaps?
    // Backend does: "desired_end = next_cue.start - min_gap".
    // Let's apply a simple pass:
    for (let i = 0; i < newCues.length - 1; i++) {
        const curr = newCues[i];
        const next = newCues[i + 1];
        if (curr.end < next.start && (next.start - curr.end) < 0.5) {
            curr.end = next.start; // Bridge small silence gaps
        }
    }

    return newCues;
}

/**
 * Efficiently finds the index of the cue active at the given time using binary search.
 * Assumes cues are sorted by start time.
 * Returns -1 if no cue is active.
 */
export function findCueIndexAtTime(cues: Cue[], time: number): number {
    let low = 0;
    let high = cues.length - 1;

    while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const cue = cues[mid];

        if (time >= cue.start && time < cue.end) {
            return mid;
        } else if (time < cue.start) {
            high = mid - 1;
        } else {
            low = mid + 1;
        }
    }

    return -1;
}

export function findCueAtTime(cues: Cue[], time: number): Cue | undefined {
    const index = findCueIndexAtTime(cues, time);
    return index !== -1 ? cues[index] : undefined;
}
