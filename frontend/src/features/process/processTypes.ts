export type TranscribeMode = "standard" | "pro";
export type TranscribeProvider = "mock" | "elevenlabs" | "groq" | "local";

export interface LastUsedSettings {
  position: number;
  size: number;
  lines: number;
  color: string;
  timestamp: number;
}
