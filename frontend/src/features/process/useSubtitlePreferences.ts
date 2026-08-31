import { useCallback, useMemo, useState } from "react";
import type { useI18n } from "@/context/I18nContext";
import type { LastUsedSettings } from "./processTypes";
import { getInitialValue, LAST_USED_SETTINGS_KEY } from "./processSettings";

type Translate = ReturnType<typeof useI18n>["t"];

function localizedSubtitleColors(t: Translate) {
  return [
    { label: t("colorYellow"), value: "#FFFF00", ass: "&H0000FFFF" },
    { label: t("colorPurple"), value: "#8B5CF6", ass: "&H00F65C8B" },
    { label: t("colorCyan"), value: "#00FFFF", ass: "&H00FFFF00" },
    { label: t("colorGreen"), value: "#00FF00", ass: "&H0000FF00" },
    { label: t("colorMagenta"), value: "#FF00FF", ass: "&H00FF00FF" },
  ];
}

function storeSubtitleSettings(settings: LastUsedSettings): void {
  try {
    localStorage.setItem(LAST_USED_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Ignore localStorage errors.
  }
}

export function useSubtitlePreferences(t: Translate) {
  const [subtitlePosition, setSubtitlePosition] = useState<number>(() =>
    getInitialValue("position", 20),
  );
  const [maxSubtitleLines, setMaxSubtitleLines] = useState(() =>
    getInitialValue("lines", 2),
  );
  const [subtitleColor, setSubtitleColor] = useState<string>(() =>
    getInitialValue("color", "#FFFF00"),
  );
  const [subtitleSize, setSubtitleSize] = useState<number>(() =>
    getInitialValue("size", 85),
  );
  const karaokeEnabled = true;
  const watermarkEnabled = false;
  const shadowStrength = 4;
  const SUBTITLE_COLORS = useMemo(() => localizedSubtitleColors(t), [t]);
  const persistSubtitleSettings = useCallback(() => {
    storeSubtitleSettings({
      position: subtitlePosition,
      size: subtitleSize,
      lines: maxSubtitleLines,
      color: subtitleColor,
      timestamp: Date.now(),
    });
  }, [maxSubtitleLines, subtitleColor, subtitlePosition, subtitleSize]);
  return {
    subtitlePosition,
    setSubtitlePosition,
    maxSubtitleLines,
    setMaxSubtitleLines,
    subtitleColor,
    setSubtitleColor,
    subtitleSize,
    setSubtitleSize,
    karaokeEnabled,
    watermarkEnabled,
    shadowStrength,
    SUBTITLE_COLORS,
    persistSubtitleSettings,
  };
}
