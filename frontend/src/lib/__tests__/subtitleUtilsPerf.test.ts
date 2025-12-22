import { resegmentCues, resetWordWidthCache } from '../subtitleUtils';
import { TranscriptionCue as Cue } from '../api';

const mockCues: Cue[] = [
    { start: 0, end: 1, text: "A B C", words: [{ start: 0, end: 0.3, text: "A" }, { start: 0.3, end: 0.6, text: "B" }, { start: 0.6, end: 1, text: "C" }] },
    { start: 1, end: 2, text: "D E F", words: [{ start: 1, end: 1.3, text: "D" }, { start: 1.3, end: 1.6, text: "E" }, { start: 1.6, end: 2, text: "F" }] }
];

describe('subtitleUtils Performance', () => {
    let measureTextSpy: jest.Mock;
    let getContextSpy: jest.SpyInstance;

    beforeEach(() => {
        resetWordWidthCache();

        measureTextSpy = jest.fn().mockImplementation((text: string) => ({
            width: text.length * 10,
        }));

        getContextSpy = jest
            .spyOn(HTMLCanvasElement.prototype, 'getContext')
            .mockImplementation(() => {
                return {
                    measureText: measureTextSpy,
                    font: '',
                } as unknown as CanvasRenderingContext2D;
            });
    });

    afterEach(() => {
        getContextSpy.mockRestore();
    });

    it('caches text measurements across multiple calls', () => {
        // First call: should measure all words
        // words: A, B, C, D, E, F (6 calls) + space (1 call) = 7 calls minimum
        resegmentCues(mockCues, 2, 100);

        const firstCallCount = measureTextSpy.mock.calls.length;
        expect(firstCallCount).toBeGreaterThan(0);

        // Second call with SAME inputs: should verify cache hits
        resegmentCues(mockCues, 2, 100);

        // Should NOT measure anything new.
        expect(measureTextSpy.mock.calls.length).toBe(firstCallCount);
    });

    it('caches text measurements across different calls with same words', () => {
        resegmentCues(mockCues, 2, 100);
        const firstCallCount = measureTextSpy.mock.calls.length;

        // Create new cues but with SAME words
        const newCues = JSON.parse(JSON.stringify(mockCues));
        resegmentCues(newCues, 3, 100); // Changed maxLines, logic runs again

        // Measurements should be cached, so no new calls
        expect(measureTextSpy.mock.calls.length).toBe(firstCallCount);
    });

    it('measures new words when font size changes', () => {
        resegmentCues(mockCues, 2, 100);
        const firstCallCount = measureTextSpy.mock.calls.length;

        // Change font size -> new cache keys -> new measurements
        resegmentCues(mockCues, 2, 200);

        expect(measureTextSpy.mock.calls.length).toBeGreaterThan(firstCallCount);
    });
});
