export type TranscriptionTier = 'standard' | 'pro';

export function resolveTranscriptionTier(
    provider: string | null | undefined,
    model: string | null | undefined,
): TranscriptionTier {
    const normalizedProvider = (provider ?? '').trim().toLowerCase();
    const normalizedModel = (model ?? '').trim().toLowerCase();

    if (normalizedModel === 'pro' || normalizedModel === 'standard') {
        return normalizedModel as TranscriptionTier;
    }
    if (normalizedModel.startsWith('gpt-4o') && normalizedModel.includes('transcribe')) {
        return 'pro';
    }
    if (normalizedModel.includes('turbo') || normalizedModel.includes('enhanced')) {
        return 'standard';
    }
    if (normalizedModel.includes('large')) {
        return 'pro';
    }
    if (normalizedProvider === 'openai') {
        return 'pro';
    }
    if (normalizedModel.includes('ultimate') || normalizedModel.includes('whisper-1') || normalizedModel.includes('openai')) {
        return 'pro';
    }
    return 'standard';
}
