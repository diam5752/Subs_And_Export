
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
    });

    it('caches results for the same cue object instance', () => {
        const cue: Cue = {
            start: 0,
            end: 1,
            text: 'hello',
            words: [{ start: 0, end: 1, text: 'hello' }]
        };

        // First call
        const result1 = resegmentCues([cue], 2, 100);
        // Second call with same parameters and object
        const result2 = resegmentCues([cue], 2, 100);

        // result1 and result2 will be DIFFERENT arrays because resegmentCues uses flatMap, which creates a new array.
        // HOWEVER, the CONTENTS of the array (the cue objects) should be reference-equal if they came from the cache.
        expect(result1).not.toBe(result2); // flatMap creates new array
        expect(result1).toHaveLength(result2.length);
        expect(result1[0]).toBe(result2[0]); // Items should be same reference (cached)

        // Third call with different parameters
        const result3 = resegmentCues([cue], 1, 200);
        expect(result3[0]).not.toBe(result1[0]); // Should be new calculation

        // Fourth call with original params again -> should be cached separately?
        // Implementation: Map<cacheKey, Result>. cacheKey depends on params.
        // Yes, it caches multiple variations per cue.
        const result4 = resegmentCues([cue], 2, 100);
        expect(result4[0]).toBe(result1[0]); // Should hit cache again
    });

    it('does not use cache for different cue object instance with same content', () => {
        const cue1: Cue = {
            start: 0,
            end: 1,
            text: 'hello',
            words: [{ start: 0, end: 1, text: 'hello' }]
        };
        const cue2: Cue = { ...cue1 }; // Copy

        const result1 = resegmentCues([cue1], 2, 100);
        const result2 = resegmentCues([cue2], 2, 100);

        // Should be structurally equal but different references because input objects are different
        expect(result1).toEqual(result2);
        expect(result1[0]).not.toBe(result2[0]); // Different cache keys (different objects)
    });

    it('mixes cached and new results correctly', () => {
        const cue1: Cue = { start: 0, end: 1, text: 'A' };
        const cue2: Cue = { start: 1, end: 2, text: 'B' };

        // Process both
        const res1 = resegmentCues([cue1, cue2], 2, 100);

        // Process again with new cue2 instance but same cue1
        const cue2New = { ...cue2 };
        const res2 = resegmentCues([cue1, cue2New], 2, 100);

        // cue1 result should be reference equal
        expect(res2[0]).toBe(res1[0]);
        // cue2 result should be new reference
        expect(res2[1]).not.toBe(res1[1]);
        expect(res2[1]).toEqual(res1[1]);
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
