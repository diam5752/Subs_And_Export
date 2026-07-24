type TranscriptionTier = 'standard' | 'pro';
type RuntimeTranscriptionProvider = 'mock' | 'elevenlabs' | 'groq' | 'local';

interface RuntimeTranscriptionSelection {
    mode: TranscriptionTier;
    provider: RuntimeTranscriptionProvider;
}

const RUNTIME_PROVIDERS = new Set<RuntimeTranscriptionProvider>([
    'mock',
    'elevenlabs',
    'groq',
    'local',
]);

export function resolveConfiguredTranscription(
    providerValue: string | null | undefined,
    modeValue: string | null | undefined,
): RuntimeTranscriptionSelection {
    const normalizedProvider = (providerValue ?? '').trim().toLowerCase();
    const provider = RUNTIME_PROVIDERS.has(normalizedProvider as RuntimeTranscriptionProvider)
        ? normalizedProvider as RuntimeTranscriptionProvider
        : 'mock';
    const requestedMode: TranscriptionTier = (modeValue ?? '').trim().toLowerCase() === 'pro'
        ? 'pro'
        : 'standard';

    // ElevenLabs is intentionally available only through the pro tier. The
    // backend independently enforces the same provider/tier contract.
    const mode: TranscriptionTier = provider === 'elevenlabs' ? 'pro' : requestedMode;
    return { mode, provider };
}

export function resolveTranscriptionTier(
    tierValue: string | null | undefined,
): TranscriptionTier {
    return (tierValue ?? '').trim().toLowerCase() === 'pro' ? 'pro' : 'standard';
}
