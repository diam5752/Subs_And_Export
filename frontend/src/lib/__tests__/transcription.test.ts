import { resolveConfiguredTranscription, resolveTranscriptionTier } from '../transcription';

describe('resolveConfiguredTranscription', () => {
    it('fails closed to the standard mock engine by default', () => {
        expect(resolveConfiguredTranscription(undefined, undefined)).toEqual({
            mode: 'standard',
            provider: 'mock',
        });
    });

    it('forces ElevenLabs onto the backend-compatible pro tier', () => {
        expect(resolveConfiguredTranscription(' elevenlabs ', 'standard')).toEqual({
            mode: 'pro',
            provider: 'elevenlabs',
        });
    });

    it('rejects unknown providers without enabling an external service', () => {
        expect(resolveConfiguredTranscription('unknown-provider', 'pro')).toEqual({
            mode: 'pro',
            provider: 'mock',
        });
    });

    it('preserves an explicitly configured supported tier', () => {
        expect(resolveConfiguredTranscription('groq', 'pro')).toEqual({
            mode: 'pro',
            provider: 'groq',
        });
    });
});

describe('resolveTranscriptionTier', () => {
    it('preserves the standard tier', () => {
        expect(resolveTranscriptionTier('standard')).toBe('standard');
    });

    it('preserves the pro tier', () => {
        expect(resolveTranscriptionTier('pro')).toBe('pro');
    });

    it('defaults absent or invalid persisted tiers to standard', () => {
        expect(resolveTranscriptionTier(null)).toBe('standard');
        expect(resolveTranscriptionTier('unknown')).toBe('standard');
    });
});
