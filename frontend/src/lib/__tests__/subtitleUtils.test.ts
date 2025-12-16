
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

    it('splits cues based on wrapped line count (not just total chars)', () => {
        // REGRESSION: user selected 3 lines but got 4 displayed due to naive total-char packing.
        const cue: Cue = {
            start: 0,
            end: 4,
            text: 'AAAAAA AAAAAA AAAAAA AAAAAA',
            words: [
                { start: 0, end: 1, text: 'AAAAAA' },
                { start: 1, end: 2, text: 'AAAAAA' },
                { start: 2, end: 3, text: 'AAAAAA' },
                { start: 3, end: 4, text: 'AAAAAA' },
            ],
        };

        const result = resegmentCues([cue], 3, 300); // very large font => low max chars per line
        expect(result).toHaveLength(2);
        expect(result[0].text).toBe('AAAAAA AAAAAA AAAAAA');
        expect(result[1].text).toBe('AAAAAA');
    });

    it('uses canvas text measurement (when available) to enforce maxLines', () => {
        // REGRESSION: char-count heuristics can under-estimate actual rendered width and allow
        // an on-screen 4th line even when "Three Lines" is selected.
        const getContextSpy = jest
            .spyOn(HTMLCanvasElement.prototype, 'getContext')
            .mockImplementation(() => {
                return {
                    measureText: (text: string) => ({
                        width: text === ' ' ? 20 : text.length * 100,
                    }),
                } as unknown as CanvasRenderingContext2D;
            });

        try {
            const cue: Cue = {
                start: 0,
                end: 4,
                text: 'AAAAAA AAAAAA AAAAAA AAAAAA',
                words: [
                    { start: 0, end: 1, text: 'AAAAAA' },
                    { start: 1, end: 2, text: 'AAAAAA' },
                    { start: 2, end: 3, text: 'AAAAAA' },
                    { start: 3, end: 4, text: 'AAAAAA' },
                ],
            };

            const result = resegmentCues([cue], 3, 100);
            expect(result).toHaveLength(2);
            expect(result[0].text).toBe('AAAAAA AAAAAA AAAAAA');
            expect(result[1].text).toBe('AAAAAA');
        } finally {
            getContextSpy.mockRestore();
        }
    });

    it('expands phrase timings into individual words', () => {
        const cue: Cue = {
            start: 0,
            end: 3,
            text: 'hello world again',
            words: [
                { start: 0, end: 2, text: 'hello world' },
                { start: 2, end: 3, text: 'again' },
            ],
        };

        const result = resegmentCues([cue], 3, 100);
        expect(result).toHaveLength(1);
        expect(result[0].words?.map((w) => w.text)).toEqual(['hello', 'world', 'again']);
        expect(result[0].words?.[0].start).toBe(0);
        expect(result[0].words?.[0].end).toBe(1);
        expect(result[0].words?.[1].start).toBe(1);
        expect(result[0].words?.[1].end).toBe(2);
    });

    it('trims whitespace from word timings (whisper-style tokens)', () => {
        const cue: Cue = {
            start: 0,
            end: 2,
            text: ' hello world',
            words: [
                { start: 0, end: 1, text: ' hello' },
                { start: 1, end: 2, text: ' world' },
            ],
        };

        const result = resegmentCues([cue], 2, 100);
        expect(result).toHaveLength(1);
        expect(result[0].words?.map((w) => w.text)).toEqual(['hello', 'world']);
    });

    it('interpolates word timings when cues have no word-level data', () => {
        const cue: Cue = {
            start: 0,
            end: 4,
            text: 'one two three',
            words: null,
        };

        const result = resegmentCues([cue], 3, 100);
        expect(result).toHaveLength(1);
        const words = result[0].words ?? [];
        expect(words.map((w) => w.text)).toEqual(['one', 'two', 'three']);
        expect(words[0].start).toBe(0);
        expect(words[words.length - 1].end).toBe(4);
        expect(words[0].end).toBeCloseTo(4 * (3 / 11), 5);
        expect(words[1].end).toBeCloseTo(4 * (6 / 11), 5);
    });
});

describe('findCueIndexAtTime', () => {
    const cues: Cue[] = [
        { start: 0, end: 1, text: "A" },
        { start: 1, end: 2, text: "B" },
        { start: 3, end: 4, text: "C" }
    ];

    it('finds cue at start time', () => {
        expect(findCueIndexAtTime(cues, 0)).toBe(0);
        expect(findCueIndexAtTime(cues, 1)).toBe(1);
        expect(findCueIndexAtTime(cues, 3)).toBe(2);
    });

    it('finds cue in middle of duration', () => {
        expect(findCueIndexAtTime(cues, 0.5)).toBe(0);
        expect(findCueIndexAtTime(cues, 1.5)).toBe(1);
        expect(findCueIndexAtTime(cues, 3.9)).toBe(2);
    });

    it('returns -1 for time before first cue', () => {
        expect(findCueIndexAtTime(cues, -1)).toBe(-1);
    });

    it('returns -1 for time in gap', () => {
        expect(findCueIndexAtTime(cues, 2.5)).toBe(-1);
    });

    it('returns -1 for time after last cue', () => {
        expect(findCueIndexAtTime(cues, 5)).toBe(-1);
    });

    it('returns -1 for exact end time (exclusive)', () => {
        expect(findCueIndexAtTime(cues, 1)).not.toBe(0); // 1 is start of B
        expect(findCueIndexAtTime(cues, 2)).toBe(-1);
    });
});

describe('findCueAtTime', () => {
    const cues: Cue[] = [
        { start: 0, end: 1, text: "A" }
    ];

    it('returns cue object when found', () => {
        expect(findCueAtTime(cues, 0.5)).toEqual(cues[0]);
    });

    it('returns undefined when not found', () => {
        expect(findCueAtTime(cues, 1.5)).toBeUndefined();
    });
});
