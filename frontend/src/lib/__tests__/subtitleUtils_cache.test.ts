
import { resegmentCues } from '../subtitleUtils';
import { TranscriptionCue as Cue } from '../api';

describe('subtitleUtils caching', () => {
    let measureTextSpy: jest.Mock;

    beforeEach(() => {
        // Reset mocks
        measureTextSpy = jest.fn((text: string) => ({ width: text.length * 10 }));
        jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => ({
            measureText: measureTextSpy,
            font: '',
        } as unknown as CanvasRenderingContext2D));
    });

    afterEach(() => {
        jest.restoreAllMocks();
    });

    it('caches measureText calls across resegmentCues invocations', () => {
        const cues: Cue[] = [{
            start: 0,
            end: 1,
            text: "TEST",
            words: [{ start: 0, end: 1, text: "TEST" }]
        }];

        // First call
        resegmentCues(cues, 1, 100);
        const callsAfterFirst = measureTextSpy.mock.calls.length;
        expect(callsAfterFirst).toBeGreaterThan(0);

        // Second call with SAME params
        resegmentCues(cues, 1, 100);
        const callsAfterSecond = measureTextSpy.mock.calls.length;

        // Without optimization, this would be 2x calls
        // With optimization, this should remain same as callsAfterFirst
        expect(callsAfterSecond).toBe(callsAfterFirst);
    });

    it('uses different cache for different font sizes', () => {
        const cues: Cue[] = [{
            start: 0,
            end: 1,
            text: "TEST",
            words: [{ start: 0, end: 1, text: "TEST" }]
        }];

        // First call size 100
        resegmentCues(cues, 1, 100);
        const calls1 = measureTextSpy.mock.calls.length;

        // Second call size 200 (should miss cache)
        resegmentCues(cues, 1, 200);
        const calls2 = measureTextSpy.mock.calls.length;

        expect(calls2).toBeGreaterThan(calls1);
    });
});
