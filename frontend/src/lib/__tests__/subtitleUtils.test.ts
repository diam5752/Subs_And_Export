
import { resegmentCues, findCueIndexAtTime, findCueAtTime, resetWordWidthCache, resetSegmentationCache } from '../subtitleUtils';
import { TranscriptionCue as Cue } from '../api';

// Mock cues
const mockCues: Cue[] = [
    { start: 0, end: 2, text: "Hello world", words: [{ start: 0, end: 1, text: "Hello" }, { start: 1, end: 2, text: "world" }] },
    { start: 2, end: 5, text: "This is a test of splitting", words: [{ start: 2, end: 3, text: "This" }, { start: 3, end: 3.5, text: "is" }, { start: 3.5, end: 4, text: "a" }, { start: 4, end: 4.5, text: "test" }, { start: 4.5, end: 4.8, text: "of" }, { start: 4.8, end: 5, text: "splitting" }] }
];

describe('resegmentCues', () => {
    beforeEach(() => {
        resetWordWidthCache();
        resetSegmentationCache();
    });

    it('should return empty list for empty input', () => {
        expect(resegmentCues([], 2, 100)).toEqual([]);
    });

    it('should return original cues if maxLines is 0 (One Word Mode)', () => {
        expect(resegmentCues(mockCues, 0, 100)).toEqual(mockCues);
    });

    it('should regroup words into new cues based on maxLines', () => {
        const result = resegmentCues(mockCues, 1, 100);
        expect(result.length).toBeGreaterThanOrEqual(2);
        expect(result[0].start).toBe(0);
        const lastCue = result[result.length - 1];
        expect(lastCue.end).toBe(mockCues[mockCues.length - 1].end);
    });

    it('should respect subtitle size scaling', () => {
        const hugeFontCues = resegmentCues(mockCues, 1, 200);
        const normalFontCues = resegmentCues(mockCues, 1, 100);
        expect(hugeFontCues.length).toBeGreaterThanOrEqual(normalFontCues.length);
    });

    it('splits cues based on wrapped line count (not just total chars)', () => {
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

        const result = resegmentCues([cue], 3, 300);
        expect(result).toHaveLength(2);
        expect(result[0].text).toBe('AAAAAA AAAAAA AAAAAA');
        expect(result[1].text).toBe('AAAAAA');
    });

    it('uses canvas text measurement (when available) to enforce maxLines', () => {
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

    it('should cache results for unchanged cues (referential equality)', () => {
        const cue: Cue = {
            start: 0,
            end: 1,
            text: 'Test Cache',
            words: [{ start: 0, end: 1, text: 'Test Cache' }]
        };

        const firstResult = resegmentCues([cue], 2, 100);
        const secondResult = resegmentCues([cue], 2, 100);

        // Should return exactly the same array reference for the inner result
        expect(firstResult[0]).toBe(secondResult[0]);
        // And the array itself (since we map it) might be different unless resegmentCues caches the whole array?
        // Wait, resegmentCues returns a new flatMap array.
        // But the objects INSIDE should be identical.
        // Actually, my implementation caches the `result` for each cue (which is an array of cues).
        // `flatMap` creates a new array containing those results.
        // So `firstResult` !== `secondResult` (the container array), but `firstResult[0]` === `secondResult[0]`.

        // Let's verify that re-running logic doesn't happen.
        // We can check by spying, but referential equality is a good proxy.
    });

    it('should invalidate cache when settings change', () => {
        const cue: Cue = {
            start: 0,
            end: 1,
            text: 'Test Cache Change',
            words: [{ start: 0, end: 1, text: 'Test Cache Change' }]
        };

        const result1 = resegmentCues([cue], 2, 100);
        const result2 = resegmentCues([cue], 1, 100); // Changed maxLines

        expect(result1[0]).not.toBe(result2[0]);
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
