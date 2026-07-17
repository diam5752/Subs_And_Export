import { resolveTranscriptionTier } from '../transcription';

describe('resolveTranscriptionTier', () => {
    it('maps Groq turbo models to standard', () => {
        expect(resolveTranscriptionTier('groq', 'whisper-large-v3-turbo')).toBe('standard');
    });

    it('maps OpenAI transcribe models to pro', () => {
        expect(resolveTranscriptionTier('openai', 'gpt-4o-transcribe')).toBe('pro');
        expect(resolveTranscriptionTier('openai', 'gpt-4o-mini-transcribe')).toBe('pro');
    });

    it('maps ElevenLabs Scribe v2 to pro', () => {
        expect(resolveTranscriptionTier('elevenlabs', 'scribe_v2')).toBe('pro');
    });

    it('falls back to provider when model name is absent', () => {
        expect(resolveTranscriptionTier('openai', null)).toBe('pro');
        expect(resolveTranscriptionTier('groq', null)).toBe('standard');
    });
});
