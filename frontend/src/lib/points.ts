export const STARTING_POINTS_BALANCE = 500;

export const PROCESS_VIDEO_DEFAULT_COST = 25;
export const PROCESS_VIDEO_MODEL_COSTS: Record<string, number> = {
    standard: 25,
    pro: 50,
};

export const FACT_CHECK_COST = 20;
export const SOCIAL_COPY_COST = 10;

export function processVideoCostForTranscribeModel(transcribeModel: string): number {
    const normalized = transcribeModel.trim().toLowerCase();
    return PROCESS_VIDEO_MODEL_COSTS[normalized] ?? PROCESS_VIDEO_DEFAULT_COST;
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
): number {
    const model = resolveTranscribeModelForSelection(provider, mode);
    return processVideoCostForTranscribeModel(model);
}

export function formatPoints(value: number): string {
    return value.toLocaleString();
}
