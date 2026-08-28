import {
    FACT_CHECK_COST,
    PROCESS_VIDEO_DEFAULT_COST,
    processVideoCostForSelection,
    processVideoCostForDuration,
    processVideoCostForTranscribeModel,
    resolveTranscribeModelForSelection,
    transcribeProviderRequiresPaidCredits,
    videoCreditQuoteForDuration,
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
        expect(processVideoCostForTranscribeModel('pro')).toBe(PROCESS_VIDEO_DEFAULT_COST);
        expect(processVideoCostForSelection('groq', 'pro')).toBe(100);
        expect(processVideoCostForSelection('groq', 'standard')).toBe(PROCESS_VIDEO_DEFAULT_COST);
        expect(processVideoCostForSelection('groq', 'pro', 180)).toBe(25);
        expect(processVideoCostForSelection('groq', 'standard', 180.001)).toBe(60);
        expect(processVideoCostForSelection('openai', 'pro', 600)).toBe(100);
    });

    it('uses exact 3, 6 and 10 minute boundaries', () => {
        expect(processVideoCostForDuration(0.1)).toBe(25);
        expect(processVideoCostForDuration(180)).toBe(25);
        expect(processVideoCostForDuration(180.001)).toBe(60);
        expect(processVideoCostForDuration(360)).toBe(60);
        expect(processVideoCostForDuration(360.001)).toBe(100);
        expect(processVideoCostForDuration(600)).toBe(100);
        expect(videoCreditQuoteForDuration(null).key).toBe('up_to_10m');
    });

    it('requires paid credits only for external transcription providers', () => {
        // REGRESSION: the frontend required purchased credits in mock mode even
        // though the backend intentionally allows promotional credits locally.
        expect(transcribeProviderRequiresPaidCredits('mock')).toBe(false);
        expect(transcribeProviderRequiresPaidCredits('local')).toBe(false);
        expect(transcribeProviderRequiresPaidCredits(null)).toBe(false);
        expect(transcribeProviderRequiresPaidCredits('groq')).toBe(true);
        expect(transcribeProviderRequiresPaidCredits('elevenlabs')).toBe(true);
    });

    it('exposes fact check cost constant', () => {
        expect(FACT_CHECK_COST).toBe(20);
    });
});
