export const STARTING_POINTS_BALANCE = 1000;

export const PROCESS_VIDEO_DEFAULT_COST = 200;
export const PROCESS_VIDEO_MODEL_COSTS: Record<string, number> = {
    turbo: 200,
    enhanced: 200,
    large: 500,
    ultimate: 500,
};

export const FACT_CHECK_COST = 100;

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

    if (normalizedProvider === 'openai') return 'openai/whisper-1';
    if (normalizedProvider === 'groq') return normalizedMode === 'ultimate' ? 'ultimate' : 'enhanced';
    if (normalizedProvider === 'local') return normalizedMode === 'balanced' ? 'medium' : 'turbo';
    return 'turbo';
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

