
import { resegmentCues, findCueIndexAtTime, findCueAtTime } from '../subtitleUtils';
import { TranscriptionCue as Cue } from '../api';

// Mock cues
const mockCues: Cue[] = [
    { start: 0, end: 2, text: "Hello world", words: [{ start: 0, end: 1, text: "Hello" }, { start: 1, end: 2, text: "world" }] },
    { start: 2, end: 5, text: "This is a test of splitting", words: [{ start: 2, end: 3, text: "This" }, { start: 3, end: 3.5, text: "is" }, { start: 3.5, end: 4, text: "a" }, { start: 4, end: 4.5, text: "test" }, { start: 4.5, end: 4.8, text: "of" }, { start: 4.8, end: 5, text: "splitting" }] }
];

describe('resegmentCues', () => {
    it('should return empty list for empty input', () => {
        expect(resegmentCues([], 2, 100)).toEqual([]);
    });

    it('should return original cues if maxLines is 0 (One Word Mode)', () => {
        expect(resegmentCues(mockCues, 0, 100)).toEqual(mockCues);
    });

    it('should regroup words into new cues based on maxLines', () => {
        // Force very small width/large font to trigger splits
        // Actually the util hardcodes 1080 width, so we rely on subtitleSize
        // maxCharsPerLine = getEffectiveMaxChars(100, 1080) -> ~28 chars

        // "Hello world" (11 chars) + "This is a test of splitting" (27 chars) joined
        // If we set 2 lines (56 chars limit approx), it might merge them?
        // But logic respects maxLines.

        // Let's try 1 line limit.
        // "Hello world This is a test of splitting" -> 38 chars
        // 1 line limit (max 28 chars) -> should split.

        const result = resegmentCues(mockCues, 1, 100);

        // Expect strict segmentation.
        // Hello world (11) -> fits
        // This is a test (14) -> fits
        // of splitting (12) -> fits
        // So we expect 3 cues maybe?

        expect(result.length).toBeGreaterThanOrEqual(2);

        // Verify continuity
        expect(result[0].start).toBe(0);
        const lastCue = result[result.length - 1];
        expect(lastCue.end).toBe(mockCues[mockCues.length - 1].end);
    });

    it('should respect subtitle size scaling', () => {
        // If font is HUGE (200%), max chars drops significantly (e.g. to 14)
        const hugeFontCues = resegmentCues(mockCues, 1, 200);
        const normalFontCues = resegmentCues(mockCues, 1, 100);

        // Huge font should result in MORE cues (shorter lines)
        expect(hugeFontCues.length).toBeGreaterThanOrEqual(normalFontCues.length);
    });
});

describe('findCueIndexAtTime', () => {
    it('should find the correct cue index', () => {
        expect(findCueIndexAtTime(mockCues, 0)).toBe(0);
        expect(findCueIndexAtTime(mockCues, 1.5)).toBe(0);
        expect(findCueIndexAtTime(mockCues, 2)).toBe(1);
        expect(findCueIndexAtTime(mockCues, 4.9)).toBe(1);
    });

    it('should return -1 if time is before first cue', () => {
        expect(findCueIndexAtTime(mockCues, -1)).toBe(-1);
    });

    it('should return -1 if time is after last cue', () => {
        expect(findCueIndexAtTime(mockCues, 6)).toBe(-1);
    });

    it('should return -1 if time is in a gap (if any)', () => {
        // Create gap
        const gapCues: Cue[] = [
            { start: 0, end: 1, text: "A" },
            { start: 2, end: 3, text: "B" }
        ];
        expect(findCueIndexAtTime(gapCues, 1.5)).toBe(-1);
    });
});

describe('findCueAtTime', () => {
    it('should find the correct cue', () => {
        expect(findCueAtTime(mockCues, 1.5)).toEqual(mockCues[0]);
    });

    it('should return undefined if no cue found', () => {
        expect(findCueAtTime(mockCues, 10)).toBeUndefined();
    });
});
