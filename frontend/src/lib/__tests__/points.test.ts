import {
    FACT_CHECK_COST,
    PROCESS_VIDEO_DEFAULT_COST,
    processVideoCostForSelection,
    processVideoCostForTranscribeModel,
    resolveTranscribeModelForSelection,
} from '@/lib/points';

describe('points pricing helpers', () => {
    it('resolves transcribe model for selection', () => {
        expect(resolveTranscribeModelForSelection('groq', 'ultimate')).toBe('ultimate');
        expect(resolveTranscribeModelForSelection('groq', 'enhanced')).toBe('enhanced');
        expect(resolveTranscribeModelForSelection('whispercpp', 'turbo')).toBe('turbo');
        expect(resolveTranscribeModelForSelection('local', 'balanced')).toBe('medium');
    });

    it('computes process video costs', () => {
        expect(processVideoCostForTranscribeModel('turbo')).toBe(PROCESS_VIDEO_DEFAULT_COST);
        expect(processVideoCostForTranscribeModel('ultimate')).toBe(500);
        expect(processVideoCostForSelection('groq', 'ultimate')).toBe(500);
        expect(processVideoCostForSelection('whispercpp', 'turbo')).toBe(PROCESS_VIDEO_DEFAULT_COST);
    });

    it('exposes fact check cost constant', () => {
        expect(FACT_CHECK_COST).toBe(100);
    });
});

