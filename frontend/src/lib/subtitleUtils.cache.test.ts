
import { resegmentCues } from './subtitleUtils';
import { TranscriptionCue as Cue } from './api';

describe('resegmentCues Caching', () => {
    let measureTextSpy: jest.Mock;
    let getContextSpy: jest.SpyInstance;

    beforeEach(() => {
        // Reset mocks
        jest.clearAllMocks();

        measureTextSpy = jest.fn((text: string) => ({
            width: text.length * 10,
        }));

        getContextSpy = jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => {
            return {
                measureText: measureTextSpy,
                font: '', // Simulate the font property setter
            } as unknown as CanvasRenderingContext2D;
        });
    });

    afterEach(() => {
        getContextSpy.mockRestore();
    });

    it('should cache measureText results across calls with same font size', () => {
        const cue: Cue = {
            start: 0,
            end: 1,
            text: 'HELLO WORLD',
            words: [
                { start: 0, end: 0.5, text: 'HELLO' },
                { start: 0.5, end: 1, text: 'WORLD' }
            ]
        };

        // First call - should measure words
        resegmentCues([cue], 2, 100);

        // Count calls. "HELLO" and "WORLD" (uppercase)
        // 2 calls expected
        const initialCalls = measureTextSpy.mock.calls.length;
        expect(initialCalls).toBeGreaterThanOrEqual(2);

        // Second call - SAME font size (100)
        resegmentCues([cue], 2, 100);

        // Should NOT have called measureText again
        expect(measureTextSpy.mock.calls.length).toBe(initialCalls);
    });

    it('should NOT cache results across DIFFERENT font sizes', () => {
        const cue: Cue = {
            start: 0,
            end: 1,
            text: 'HELLO',
            words: [
                { start: 0, end: 1, text: 'HELLO' }
            ]
        };

        // Call with size 100
        resegmentCues([cue], 2, 100);
        const callsAfterFirst = measureTextSpy.mock.calls.length;

        // Call with size 200
        resegmentCues([cue], 2, 200);
        const callsAfterSecond = measureTextSpy.mock.calls.length;

        expect(callsAfterSecond).toBeGreaterThan(callsAfterFirst);
    });
});
