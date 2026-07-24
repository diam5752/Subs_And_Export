export const PROCESS_VIDEO_DEFAULT_COST = 100;
const PROCESS_VIDEO_MODEL_COSTS: Record<string, number> = {
    standard: PROCESS_VIDEO_DEFAULT_COST,
    pro: PROCESS_VIDEO_DEFAULT_COST,
};

interface VideoCreditQuote {
    key: 'up_to_3m' | 'up_to_6m' | 'up_to_10m';
    maxDurationSeconds: number;
    credits: number;
}

export const VIDEO_CREDIT_BRACKETS: readonly VideoCreditQuote[] = [
    { key: 'up_to_3m', maxDurationSeconds: 180, credits: 30 },
    { key: 'up_to_6m', maxDurationSeconds: 360, credits: 60 },
    { key: 'up_to_10m', maxDurationSeconds: 600, credits: 100 },
] as const;

export const FACT_CHECK_COST = 20;
export const SOCIAL_COPY_COST = 10;

export function processVideoCostForTranscribeModel(transcribeModel: string): number {
    const normalized = transcribeModel.trim().toLowerCase();
    return PROCESS_VIDEO_MODEL_COSTS[normalized] ?? PROCESS_VIDEO_DEFAULT_COST;
}

export function videoCreditQuoteForDuration(
    durationSeconds: number | null | undefined,
): VideoCreditQuote {
    if (
        typeof durationSeconds !== 'number'
        || !Number.isFinite(durationSeconds)
        || durationSeconds <= 0
    ) {
        return VIDEO_CREDIT_BRACKETS[VIDEO_CREDIT_BRACKETS.length - 1];
    }
    const quote = VIDEO_CREDIT_BRACKETS.find(
        (candidate) => durationSeconds <= candidate.maxDurationSeconds,
    );
    return quote ?? VIDEO_CREDIT_BRACKETS[VIDEO_CREDIT_BRACKETS.length - 1];
}

export function processVideoCostForDuration(
    durationSeconds: number | null | undefined,
): number {
    return videoCreditQuoteForDuration(durationSeconds).credits;
}

export function resolveTranscribeModelForSelection(
    provider: string | null | undefined,
    mode: string | null | undefined,
): string {
    const normalizedProvider = (provider ?? '').trim().toLowerCase();
    const normalizedMode = (mode ?? '').trim().toLowerCase();

    if (normalizedMode === 'pro') return 'pro';
    if (normalizedMode === 'standard') return 'standard';
    if (normalizedMode.includes('turbo') || normalizedMode.includes('enhanced')) return 'standard';
    if (normalizedMode.includes('large')) return 'pro';
    if (normalizedProvider === 'openai') return 'pro';
    return 'standard';
}

export function processVideoCostForSelection(
    provider: string | null | undefined,
    mode: string | null | undefined,
    durationSeconds?: number | null,
): number {
    // Provider and model no longer change the public video price. Keep them in
    // the signature for compatibility with existing callers while duration is
    // the sole pricing authority.
    void provider;
    void mode;
    return processVideoCostForDuration(durationSeconds);
}

export function formatPoints(value: number): string {
    return value.toLocaleString();
}
