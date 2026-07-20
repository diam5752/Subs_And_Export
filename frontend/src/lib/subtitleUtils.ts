import { TranscriptionCue as Cue, TranscriptionWordTiming } from './api';

// Configuration matching backend config.py
const DEFAULT_SUB_FONT_SIZE = 62;

const MAX_SUB_LINE_CHARS = 26; // Safe characters per line for Greek uppercase (reduced from 28)

const BASE_VIDEO_WIDTH = 1080;
const SAFE_MARGIN_PCT = 0.074; // Match SubtitleOverlay left/right (7.4%).
const BASE_SAFE_WIDTH = BASE_VIDEO_WIDTH * (1 - SAFE_MARGIN_PCT * 2);
const OVERLAY_FONT_FAMILY = "'Arial Black', 'Montserrat', sans-serif";
const OVERLAY_FONT_WEIGHT = 900;

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

type TextMeasurer = {
    measureText: (text: string) => number;
    spaceWidth: number;
    maxLineWidth: number;
};

const MAX_CACHE_SIZE = 10000;
const _wordWidthCache = new Map<string, number>();

export function resetWordWidthCache() {
    _wordWidthCache.clear();
}

let _sharedMeasurerCanvas: HTMLCanvasElement | null = null;

function getSharedMeasurerCanvas(): HTMLCanvasElement | null {
    /* istanbul ignore next -- exercised in browser or via canvas mocking */
    if (typeof document === 'undefined') return null;

    /* istanbul ignore next -- exercised in browser or via canvas mocking */
    if (!_sharedMeasurerCanvas) {
        _sharedMeasurerCanvas = document.createElement('canvas');
    }
    return _sharedMeasurerCanvas;
}

function createTextMeasurer(fontSizePercent: number): TextMeasurer | null {
    const canvas = getSharedMeasurerCanvas();
    if (!canvas) return null;

    /* istanbul ignore next -- exercised in browser or via canvas mocking */
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;

    const fontSizePx = Math.max(1, Math.round(DEFAULT_SUB_FONT_SIZE * (fontSizePercent / 100)));
    // Add stroke width buffer? 
    // The stroke is around 3px scaled.
    // Using a conservative 90% width below handles this implicitly.
    ctx.font = `${OVERLAY_FONT_WEIGHT} ${fontSizePx}px ${OVERLAY_FONT_FAMILY}`;

    const measureText = (text: string) => {
        const key = `${fontSizePx}:${text}`;
        const cached = _wordWidthCache.get(key);
        if (cached !== undefined) return cached;

        const width = ctx.measureText(text).width;

        if (_wordWidthCache.size >= MAX_CACHE_SIZE) {
            const firstKey = _wordWidthCache.keys().next().value;
            if (firstKey) _wordWidthCache.delete(firstKey);
        }

        _wordWidthCache.set(key, width);
        return width;
    };

    return {
        measureText,
        spaceWidth: measureText(' '),
        // Use a slightly conservative width to avoid edge-case overflows from measurement differences.
        // Reduced from 0.98 to 0.90 to be safer against stroke width and anti-aliasing differences.
        maxLineWidth: BASE_SAFE_WIDTH * 0.90,
    };
}

/**
 * Flatten all words from a list of cues into a single timeline.
 */
function expandPhraseTiming(word: TranscriptionWordTiming): TranscriptionWordTiming[] {
    const normalized = word.text.trim();
    if (!normalized) return [];

    const parts = normalized.split(/\s+/).filter(Boolean);
    if (parts.length <= 1) return [{ ...word, text: normalized }];

    const totalDuration = word.end - word.start;
    const totalChars = normalized.replace(/\s+/g, '').length;
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
    const cueWords = cue.text.trim().split(/\s+/).filter(Boolean);
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

function chunkTimedWordsByWidth(
    words: TranscriptionWordTiming[],
    maxLines: number,
    measurer: TextMeasurer
): TranscriptionWordTiming[][] {
    const chunks: TranscriptionWordTiming[][] = [];
    if (words.length === 0) return chunks;

    let currentChunk: TranscriptionWordTiming[] = [];
    let currentLines = 1;
    let currentLineWidth = 0;

    for (const word of words) {
        const normalizedText = word.text.trim();
        if (!normalizedText) continue;

        const renderText = normalizedText.toUpperCase();
        const wordWidth = measurer.measureText(renderText);

        const needsSpace = currentLineWidth > 0;
        const spaceWidth = needsSpace ? measurer.spaceWidth : 0;

        if (currentLineWidth + spaceWidth + wordWidth <= measurer.maxLineWidth || currentLineWidth === 0) {
            currentLineWidth += spaceWidth + wordWidth;
        } else {
            // Wrap to next line; if no room, start a new chunk/cue.
            if (currentChunk.length > 0 && currentLines + 1 > maxLines) {
                chunks.push(currentChunk);
                currentChunk = [];
                currentLines = 1;
            } else {
                currentLines += 1;
            }
            currentLineWidth = wordWidth;
        }

        currentChunk.push({ ...word, text: normalizedText });
    }

    if (currentChunk.length > 0) chunks.push(currentChunk);
    return chunks;
}

/**
 * Re-segment cues to fit within maxLines constraints.
 * Ports backend `_split_long_cues` logic.
 * Processes each cue individually to preserve original time boundaries/silences.
 */
export function resegmentCues(
    originalCues: Cue[],
    maxLines: number,
    fontSizePercent: number
): Cue[] {
    if (!originalCues || originalCues.length === 0) return [];
    if (maxLines === 0) return originalCues; // Handled by SubtitleOverlay specially ("One Word" mode)

    const measurer = createTextMeasurer(fontSizePercent);
    const effectiveMaxChars = getEffectiveMaxChars(fontSizePercent);

    return originalCues.flatMap((cue) => {
        // 1. Get words for this SPECIFIC cue (real or interpolated)
        let cueWords: TranscriptionWordTiming[] = [];
        if (cue.words && cue.words.length > 0) {
            cue.words.forEach((word) => {
                cueWords.push(...expandPhraseTiming(word));
            });
        } else {
            cueWords = interpolateWordsFromCueText(cue);
        }

        if (cueWords.length === 0) return [cue];

        // 2. Chunk ONLY this cue's words
        const wordChunks = measurer
            ? chunkTimedWordsByWidth(cueWords, maxLines, measurer)
            : chunkTimedWords(cueWords, effectiveMaxChars, maxLines);

        // 3. Create new cues from chunks
        return wordChunks
            .filter((chunkWords) => chunkWords.length > 0)
            .map((chunkWords) => {
                const first = chunkWords[0];
                const last = chunkWords[chunkWords.length - 1];

                // Ensure the last chunk extends to the original cue end time 
                // to match backend logic (avoid shortening due to word timing precision)
                const isLastChunk = chunkWords === wordChunks[wordChunks.length - 1];
                const endTime = isLastChunk ? Math.max(last.end, cue.end) : last.end;

                return {
                    start: first.start,
                    end: endTime,
                    text: chunkWords.map((w) => w.text).join(' '),
                    words: chunkWords,
                };
            });
    });
}

/**
 * Efficiently finds the index of the cue active at the given time using binary search.
 * Assumes cues are sorted by start time.
 * Returns -1 if no cue is active.
 *
 * @param hintIndex Optimization hint: index of the last found cue.
 *                  Checks this and the next index before binary search.
 */
export function findCueIndexAtTime(cues: Cue[], time: number, hintIndex = -1): number {
    // Optimization: Check hint index first (and next one)
    // This reduces lookup from O(log N) to O(1) for linear playback
    if (hintIndex >= 0 && hintIndex < cues.length) {
        // Check exact hint
        if (time >= cues[hintIndex].start && time < cues[hintIndex].end) {
            return hintIndex;
        }
        // Check next (common case for linear playback)
        const nextIndex = hintIndex + 1;
        if (nextIndex < cues.length) {
            if (time >= cues[nextIndex].start && time < cues[nextIndex].end) {
                return nextIndex;
            }
        }
    }

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

export function findCueAtTime(cues: Cue[], time: number, hintIndex = -1): Cue | undefined {
    const index = findCueIndexAtTime(cues, time, hintIndex);
    return index !== -1 ? cues[index] : undefined;
}
