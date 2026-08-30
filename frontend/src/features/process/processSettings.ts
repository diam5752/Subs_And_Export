import {
  SUBTITLE_POSITION_MAX,
  SUBTITLE_POSITION_MIN,
} from "@/lib/subtitleUtils";
import type { LastUsedSettings } from "./processTypes";

export const LAST_USED_SETTINGS_KEY = "lastUsedSubtitleSettings";

function clampNumber(value: unknown, min: number, max: number): number | null {
  const numberValue = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numberValue)) return null;
  return Math.max(min, Math.min(max, numberValue));
}

function normalizeStoredSetting<T>(
  key: keyof LastUsedSettings,
  rawValue: unknown,
  defaultValue: T,
): T {
  if (key === "position") {
    return (clampNumber(
      rawValue,
      SUBTITLE_POSITION_MIN,
      SUBTITLE_POSITION_MAX,
    ) ?? defaultValue) as T;
  }
  if (key === "size") {
    return (clampNumber(rawValue, 50, 150) ?? defaultValue) as T;
  }
  if (key === "lines") {
    return (clampNumber(rawValue, 0, 4) ?? defaultValue) as T;
  }
  if (key === "color") {
    const color = typeof rawValue === "string" ? rawValue.trim() : "";
    return (color || defaultValue) as T;
  }
  return rawValue as T;
}

export function getInitialValue<T>(
  key: keyof LastUsedSettings,
  defaultValue: T,
): T {
  if (typeof window === "undefined") return defaultValue;
  try {
    const stored = localStorage.getItem(LAST_USED_SETTINGS_KEY);
    if (!stored) return defaultValue;
    const parsed = JSON.parse(stored) as Partial<
      Record<keyof LastUsedSettings, unknown>
    > | null;
    const rawValue = parsed?.[key];
    if (rawValue === undefined) return defaultValue;
    return normalizeStoredSetting(key, rawValue, defaultValue);
  } catch {
    return defaultValue;
  }
}

export function videoQualityForResolution(
  resolution: string,
  subtitleFileFormats: ReadonlySet<string>,
): "low size" | "balanced" | "high quality" | undefined {
  if (subtitleFileFormats.has(resolution)) return undefined;
  if (resolution === "720x1280") return "low size";
  if (resolution === "1080x1920") return "high quality";
  return "balanced";
}
