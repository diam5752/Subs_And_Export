export type TranscribeMode = 'standard' | 'pro';
export type TranscribeProvider = 'mock' | 'elevenlabs' | 'groq' | 'local';

export interface StylePreset {
    id: string;
    name: string;
    description: string;
    emoji: string;
    settings: {
        position: number;
        size: number;
        lines: number;
        color: string;
        karaoke: boolean;
        watermark: boolean;
    };
    colorClass: string;
}

export interface LastUsedSettings {
    position: number;
    size: number;
    lines: number;
    color: string;
    karaoke: boolean;
    watermark?: boolean;
    timestamp: number;
}
