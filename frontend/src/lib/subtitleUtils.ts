import { TranscriptionCue as Cue } from './api';

// Configuration matching backend config.py
const DEFAULT_SUB_FONT_SIZE = 62;
const DEFAULT_WIDTH = 1080; // Default video width for character count calculations

const MAX_SUB_LINE_CHARS = 28; // Safe characters per line for Greek uppercase

/**
 * Estimate the effective character limit per line based on font size and video width.
 * Mirrored from backend `_effective_max_chars`
 */
function getEffectiveMaxChars(fontSizePercent: number, videoWidth: number): number {
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
function getAllWords(cues: Cue[]): { start: number; end: number; text: string }[] {
    const words: { start: number; end: number; text: string }[] = [];
    cues.forEach(cue => {
        if (cue.words) {
            words.push(...cue.words);
        } else {
            // Fallback for cues without word timings (just one big "word")
            words.push({ start: cue.start, end: cue.end, text: cue.text });
        }
    });
    return words.sort((a, b) => a.start - b.start);
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

    const maxCharsPerLine = getEffectiveMaxChars(fontSizePercent, DEFAULT_WIDTH);

    // We want to group words into Cues such that:
    // - Total chars <= maxLines * maxCharsPerLine
    // - Ideally logical breaks (but greedy for now to match backend)
    // - New cue starts where previous ended (or at next word start)

    const newCues: Cue[] = [];
    let currentChunkWords: typeof allWords = [];
    let currentChunkLen = 0;

    // Helper to flush current chunk
    const flushChunk = () => {
        if (currentChunkWords.length === 0) return;

        const first = currentChunkWords[0];
        const last = currentChunkWords[currentChunkWords.length - 1];

        // Simple text construction
        const text = currentChunkWords.map(w => w.text).join(' ');

        newCues.push({
            start: first.start,
            end: last.end, // In backend we extended to original cue end? 
            // Here we treat words as truth. 
            // Improvement: Extend 'end' to next word's 'start' to avoid flickering?
            // For now, tight bounding.
            text: text,
            words: [...currentChunkWords]
        });

        currentChunkWords = [];
        currentChunkLen = 0;
    };

    // 2. Greedy Packing
    const totalMaxChars = maxCharsPerLine * maxLines;

    for (const word of allWords) {
        const wordLen = word.text.length + 1; // +1 for space

        // If adding this word exceeds limits
        if (currentChunkLen + wordLen > totalMaxChars && currentChunkWords.length > 0) {
            flushChunk();
        }

        currentChunkWords.push(word);
        currentChunkLen += wordLen;

        // Handling for "newline" logic within a cue?
        // The backend _chunk_items actually splits into multiple Cues (events).
        // It does NOT insert \N inside a single cue if it exceeds max_lines.
        // It creates a NEW event.
        // So yes, we flush and start new cue.
    }
    flushChunk();

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
 * Finds the index of the cue that covers the given time using binary search.
 * Returns -1 if no cue covers the time.
 * Assumes cues are sorted by start time.
 */
export function findCueIndexAtTime(cues: Cue[], time: number): number {
    let low = 0;
    let high = cues.length - 1;

    while (low <= high) {
        const mid = (low + high) >>> 1;
        const cue = cues[mid];

        if (time >= cue.start && time < cue.end) {
            return mid;
        }
        if (time < cue.start) {
            high = mid - 1;
        } else {
            low = mid + 1;
        }
    }
    return -1;
}

/**
 * Finds the cue that covers the given time using binary search.
 * Returns undefined if no cue covers the time.
 */
export function findCueAtTime(cues: Cue[], time: number): Cue | undefined {
    const index = findCueIndexAtTime(cues, time);
    return index !== -1 ? cues[index] : undefined;
}
