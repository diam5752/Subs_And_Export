import { TranscriptionCue as Cue, TranscriptionWordTiming } from './api';

// Configuration matching backend config.py
const DEFAULT_SUB_FONT_SIZE = 62;

const MAX_SUB_LINE_CHARS = 26; // Safe characters per line for Greek uppercase (reduced from 28)

const BASE_VIDEO_WIDTH = 1080;
const SAFE_MARGIN_PCT = 0.074; // Match SubtitleOverlay left/right (7.4%).
const BASE_SAFE_WIDTH = BASE_VIDEO_WIDTH * (1 - SAFE_MARGIN_PCT * 2);
const OVERLAY_FONT_FAMILY = "'Arial Black', 'Montserrat', sans-serif";
const OVERLAY_FONT_WEIGHT = 900;
const STRONG_BREAK_PUNCTUATION = new Set(['.', '!', '?', ';', ':', '…']);
const SOFT_BREAK_PUNCTUATION = new Set([',']);

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
const COMBINING_MARKS_REGEX = /\p{M}+/gu;

export function normalizeSubtitleText(text: string): string {
    return text.normalize('NFD').replace(COMBINING_MARKS_REGEX, '').toUpperCase();
}

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

    const sampleWidth = measureText('MMMM');
    if (!Number.isFinite(sampleWidth) || sampleWidth <= 0) {
        return null;
    }

    return {
        measureText,
        spaceWidth: measureText(' '),
        // Use a slightly conservative width to avoid edge-case overflows from measurement differences.
        // Reduced from 0.98 to 0.90 to be safer against stroke width and anti-aliasing differences.
        maxLineWidth: BASE_SAFE_WIDTH * 0.90,
    };
}

function lineTextLength(texts: string[]): number {
    if (texts.length === 0) return 0;
    return texts.reduce((sum, text) => sum + text.length, 0) + Math.max(0, texts.length - 1);
}

function lineBreakBonus(text: string): number {
    const stripped = text.trimEnd();
    if (!stripped) return 0;
    const tail = stripped[stripped.length - 1];
    if (STRONG_BREAK_PUNCTUATION.has(tail)) return 0.45;
    if (SOFT_BREAK_PUNCTUATION.has(tail)) return 0.18;
    return 0;
}

function wrapItemsBalanced<T>(
    items: T[],
    getText: (item: T) => string,
    maxChars: number,
): T[][] {
    if (items.length === 0) return [];

    const safeMaxChars = Math.max(1, maxChars);
    const texts = items.map(getText);
    const cache = new Map<number, { cost: number; breaks: number[] }>();

    const bestLayout = (startIndex: number): { cost: number; breaks: number[] } => {
        if (startIndex >= items.length) {
            return { cost: 0, breaks: [] };
        }

        const cached = cache.get(startIndex);
        if (cached) return cached;

        let bestCost = Number.POSITIVE_INFINITY;
        let bestBreaks: number[] = [Math.min(startIndex + 1, items.length)];
        let runningLength = 0;

        for (let endIndex = startIndex; endIndex < items.length; endIndex += 1) {
            const text = texts[endIndex];
            runningLength = endIndex === startIndex ? text.length : runningLength + 1 + text.length;
            const overflow = Math.max(0, runningLength - safeMaxChars);

            if (overflow > 0 && endIndex > startIndex) {
                break;
            }

            const isLastLine = endIndex === items.length - 1;
            const visibleLength = Math.min(runningLength, safeMaxChars);
            const slack = Math.max(0, safeMaxChars - visibleLength);
            const gapWeight = isLastLine ? 0.35 : 1;
            let lineCost = overflow * overflow * 1000 + slack * slack * gapWeight;
            if (!isLastLine) {
                lineCost -= lineBreakBonus(text);
            }

            const next = bestLayout(endIndex + 1);
            const totalCost = lineCost + next.cost;
            if (totalCost < bestCost) {
                bestCost = totalCost;
                bestBreaks = [endIndex + 1, ...next.breaks];
            }
        }

        const result = { cost: bestCost, breaks: bestBreaks };
        cache.set(startIndex, result);
        return result;
    };

    const { breaks } = bestLayout(0);
    const lines: T[][] = [];
    let startIndex = 0;
    for (const endIndex of breaks) {
        lines.push(items.slice(startIndex, endIndex));
        startIndex = endIndex;
    }
    return lines.length > 0 ? lines : [items.slice()];
}

function wrapItemsByWidth<T>(
    items: T[],
    getText: (item: T) => string,
    measurer: TextMeasurer,
): T[][] {
    if (items.length === 0) return [];

    const texts = items.map(getText);
    const widths = texts.map((text) => measurer.measureText(text));
    const cache = new Map<number, { cost: number; breaks: number[] }>();

    const bestLayout = (startIndex: number): { cost: number; breaks: number[] } => {
        if (startIndex >= items.length) {
            return { cost: 0, breaks: [] };
        }

        const cached = cache.get(startIndex);
        if (cached) return cached;

        let bestCost = Number.POSITIVE_INFINITY;
        let bestBreaks: number[] = [Math.min(startIndex + 1, items.length)];
        let runningWidth = 0;

        for (let endIndex = startIndex; endIndex < items.length; endIndex += 1) {
            runningWidth = endIndex === startIndex
                ? widths[endIndex]
                : runningWidth + measurer.spaceWidth + widths[endIndex];

            const overflow = Math.max(0, runningWidth - measurer.maxLineWidth);
            if (overflow > 0 && endIndex > startIndex) {
                break;
            }

            const isLastLine = endIndex === items.length - 1;
            const visibleWidth = Math.min(runningWidth, measurer.maxLineWidth);
            const slack = Math.max(0, measurer.maxLineWidth - visibleWidth);
            const gapWeight = isLastLine ? 0.35 : 1;
            let lineCost = overflow * overflow * 1000 + slack * slack * gapWeight;
            if (!isLastLine) {
                lineCost -= lineBreakBonus(texts[endIndex]) * measurer.maxLineWidth;
            }

            const next = bestLayout(endIndex + 1);
            const totalCost = lineCost + next.cost;
            if (totalCost < bestCost) {
                bestCost = totalCost;
                bestBreaks = [endIndex + 1, ...next.breaks];
            }
        }

        const result = { cost: bestCost, breaks: bestBreaks };
        cache.set(startIndex, result);
        return result;
    };

    const { breaks } = bestLayout(0);
    const lines: T[][] = [];
    let startIndex = 0;
    for (const endIndex of breaks) {
        lines.push(items.slice(startIndex, endIndex));
        startIndex = endIndex;
    }
    return lines.length > 0 ? lines : [items.slice()];
}

function scoreWrappedTextLines(
    wrappedLines: string[][],
    maxChars: number,
    maxLines: number,
    remainingItems: number,
): number {
    if (wrappedLines.length === 0) return Number.NEGATIVE_INFINITY;

    const safeMaxChars = Math.max(1, maxChars);
    const safeMaxLines = Math.max(1, maxLines);
    const lengths = wrappedLines.map((line) => lineTextLength(line));
    const totalTokens = wrappedLines.reduce((sum, line) => sum + line.length, 0);
    const fillRatio = lengths.reduce((sum, length) => sum + Math.min(length, safeMaxChars), 0) / (safeMaxLines * safeMaxChars);
    const imbalance = lengths.length > 1 ? (Math.max(...lengths) - Math.min(...lengths)) / safeMaxChars : 0;
    const unusedLinePenalty = remainingItems > 0 && wrappedLines.length < safeMaxLines
        ? ((safeMaxLines - wrappedLines.length) / safeMaxLines) * 0.25
        : 0;
    const singleTokenPenalty = remainingItems > 0 && totalTokens === 1 ? 0.45 : 0;

    let tailPenalty = 0;
    if (remainingItems === 1) {
        tailPenalty = 0.6;
    } else if (remainingItems === 2) {
        tailPenalty = 0.18;
    }

    const lastLine = wrappedLines[wrappedLines.length - 1] ?? [];
    const lastToken = lastLine[lastLine.length - 1] ?? '';
    return fillRatio - (imbalance * 0.35) - unusedLinePenalty - singleTokenPenalty - tailPenalty + lineBreakBonus(lastToken);
}

function lineWidth(texts: string[], measurer: TextMeasurer): number {
    if (texts.length === 0) return 0;
    return texts.reduce((sum, text) => sum + measurer.measureText(text), 0) + Math.max(0, texts.length - 1) * measurer.spaceWidth;
}

function scoreWrappedWidthLines(
    wrappedLines: TranscriptionWordTiming[][],
    measurer: TextMeasurer,
    maxLines: number,
    remainingItems: number,
): number {
    if (wrappedLines.length === 0) return Number.NEGATIVE_INFINITY;

    const widths = wrappedLines.map((line) => lineWidth(line.map((word) => word.text), measurer));
    const safeMaxLines = Math.max(1, maxLines);
    const totalTokens = wrappedLines.reduce((sum, line) => sum + line.length, 0);
    const fillRatio = widths.reduce((sum, width) => sum + Math.min(width, measurer.maxLineWidth), 0) / (safeMaxLines * measurer.maxLineWidth);
    const imbalance = widths.length > 1 ? (Math.max(...widths) - Math.min(...widths)) / measurer.maxLineWidth : 0;
    const unusedLinePenalty = remainingItems > 0 && wrappedLines.length < safeMaxLines
        ? ((safeMaxLines - wrappedLines.length) / safeMaxLines) * 0.25
        : 0;
    const singleTokenPenalty = remainingItems > 0 && totalTokens === 1 ? 0.45 : 0;

    let tailPenalty = 0;
    if (remainingItems === 1) {
        tailPenalty = 0.6;
    } else if (remainingItems === 2) {
        tailPenalty = 0.18;
    }

    const lastLine = wrappedLines[wrappedLines.length - 1] ?? [];
    const lastToken = lastLine[lastLine.length - 1]?.text ?? '';
    return fillRatio - (imbalance * 0.35) - unusedLinePenalty - singleTokenPenalty - tailPenalty + lineBreakBonus(lastToken);
}

/**
 * Flatten all words from a list of cues into a single timeline.
 */
function expandPhraseTiming(word: TranscriptionWordTiming): TranscriptionWordTiming[] {
    const normalized = normalizeSubtitleText(word.text).trim();
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
    const normalizedCueText = normalizeSubtitleText(cue.text).trim();
    const cueWords = normalizedCueText.split(/\s+/).filter(Boolean);
    if (cueWords.length === 0) return [];

    const cueDuration = cue.end - cue.start;
    const totalChars = normalizedCueText.replace(/\s+/g, '').length;
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
    const cache = new Map<number, { score: number; breaks: number[] }>();

    const bestChunking = (startIndex: number): { score: number; breaks: number[] } => {
        if (startIndex >= words.length) {
            return { score: 0, breaks: [] };
        }

        const cached = cache.get(startIndex);
        if (cached) return cached;

        let bestScore = Number.NEGATIVE_INFINITY;
        let bestBreaks: number[] = [Math.min(startIndex + 1, words.length)];
        const candidateTexts: string[] = [];

        for (let endIndex = startIndex; endIndex < words.length; endIndex += 1) {
            candidateTexts.push(words[endIndex].text);
            const wrapped = wrapItemsBalanced(candidateTexts, (text) => text, maxChars);
            const wrappedCount = wrapped.length;

            if (wrappedCount > maxLines && endIndex > startIndex) {
                break;
            }

            const chunkScore = scoreWrappedTextLines(wrapped, maxChars, maxLines, words.length - endIndex - 1);
            const next = bestChunking(endIndex + 1);
            const totalScore = chunkScore + next.score;
            if (totalScore >= bestScore) {
                bestScore = totalScore;
                bestBreaks = [endIndex + 1, ...next.breaks];
            }
        }

        const result = { score: bestScore, breaks: bestBreaks };
        cache.set(startIndex, result);
        return result;
    };

    const { breaks } = bestChunking(0);
    let startIndex = 0;
    for (const endIndex of breaks) {
        chunks.push(words.slice(startIndex, endIndex));
        startIndex = endIndex;
    }

    return chunks;
}

function chunkTimedWordsByWidth(
    words: TranscriptionWordTiming[],
    maxLines: number,
    measurer: TextMeasurer
): TranscriptionWordTiming[][] {
    const chunks: TranscriptionWordTiming[][] = [];
    if (words.length === 0) return chunks;
    const cache = new Map<number, { score: number; breaks: number[] }>();

    const bestChunking = (startIndex: number): { score: number; breaks: number[] } => {
        if (startIndex >= words.length) {
            return { score: 0, breaks: [] };
        }

        const cached = cache.get(startIndex);
        if (cached) return cached;

        let bestScore = Number.NEGATIVE_INFINITY;
        let bestBreaks: number[] = [Math.min(startIndex + 1, words.length)];

        for (let endIndex = startIndex; endIndex < words.length; endIndex += 1) {
            const candidate = words.slice(startIndex, endIndex + 1);
            const wrapped = wrapItemsByWidth(candidate, (word) => word.text, measurer);
            const wrappedCount = wrapped.length;

            if (wrappedCount > maxLines && endIndex > startIndex) {
                break;
            }

            const chunkScore = scoreWrappedWidthLines(wrapped, measurer, maxLines, words.length - endIndex - 1);
            const next = bestChunking(endIndex + 1);
            const totalScore = chunkScore + next.score;
            if (totalScore >= bestScore) {
                bestScore = totalScore;
                bestBreaks = [endIndex + 1, ...next.breaks];
            }
        }

        const result = { score: bestScore, breaks: bestBreaks };
        cache.set(startIndex, result);
        return result;
    };

    const { breaks } = bestChunking(0);
    let startIndex = 0;
    for (const endIndex of breaks) {
        chunks.push(words.slice(startIndex, endIndex));
        startIndex = endIndex;
    }

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

        if (cueWords.length === 0) {
            return [{ ...cue, text: normalizeSubtitleText(cue.text) }];
        }

        const preparedWords = cueWords
            .map((word) => ({ ...word, text: normalizeSubtitleText(word.text).trim() }))
            .filter((word) => word.text.length > 0);

        if (preparedWords.length === 0) {
            return [{ ...cue, text: normalizeSubtitleText(cue.text) }];
        }

        // 2. Chunk ONLY this cue's words
        const wordChunks = measurer
            ? chunkTimedWordsByWidth(preparedWords, maxLines, measurer)
            : chunkTimedWords(preparedWords, effectiveMaxChars, maxLines);

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
