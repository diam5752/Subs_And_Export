import {
    FACT_CHECK_COST,
    PROCESS_VIDEO_DEFAULT_COST,
    processVideoCostForSelection,
    processVideoCostForTranscribeModel,
    resolveTranscribeModelForSelection,
} from '@/lib/points';

describe('points pricing helpers', () => {
    it('resolves transcribe model for selection', () => {
        expect(resolveTranscribeModelForSelection('groq', 'standard')).toBe('standard');
        expect(resolveTranscribeModelForSelection('groq', 'pro')).toBe('pro');
        expect(resolveTranscribeModelForSelection('groq', 'whisper-large-v3')).toBe('pro');
        expect(resolveTranscribeModelForSelection('groq', 'whisper-large-v3-turbo')).toBe('standard');
        expect(resolveTranscribeModelForSelection('groq', null)).toBe('standard');
    });

    it('computes process video costs', () => {
        expect(processVideoCostForTranscribeModel('standard')).toBe(PROCESS_VIDEO_DEFAULT_COST);
        expect(processVideoCostForTranscribeModel('pro')).toBe(50);
        expect(processVideoCostForSelection('groq', 'pro')).toBe(50);
        expect(processVideoCostForSelection('groq', 'standard')).toBe(PROCESS_VIDEO_DEFAULT_COST);
    });

    it('exposes fact check cost constant', () => {
        expect(FACT_CHECK_COST).toBe(20);
    });
});
