import { useState } from "react";
import { useI18n } from "@/context/I18nContext";
import styles from "./UploadLanding.module.css";

const SAMPLE_COLORS = [
  { value: "#FFFF00", label: "colorYellow" },
  { value: "#00FFFF", label: "colorCyan" },
  { value: "#8B5CF6", label: "colorPurple" },
] as const;

export function CaptionSample() {
  const { t } = useI18n();
  const [color, setColor] = useState<string>(SAMPLE_COLORS[0].value);

  return (
    <aside className={styles.sample} aria-label={t("captionSampleLabel")}>
      <div className={styles.sampleHeading}>
        <span className={styles.cc} aria-hidden="true">
          CC
        </span>
        <span>{t("captionSampleLabel")}</span>
        <span className={styles.sampleFormat}>9:16</span>
      </div>
      <div className={styles.sampleCanvas}>
        <div className={styles.waveform} aria-hidden="true">
          {[18, 28, 45, 32, 60, 42, 72, 48, 30, 56, 38, 22, 44, 62, 36, 18].map(
            (height, index) => (
              <i key={index} style={{ height }} />
            ),
          )}
        </div>
        <p className={styles.sampleCaption}>
          {t("captionSampleLine")}
          <br />
          <span style={{ color }}>{t("captionSampleHighlight")}</span>
        </p>
        <span className={styles.sampleTiming}>{t("captionSampleTiming")}</span>
      </div>
      <div className={styles.sampleControls}>
        <span id="sample-color-label">{t("captionSampleColor")}</span>
        <div
          className={styles.swatches}
          role="group"
          aria-labelledby="sample-color-label"
        >
          {SAMPLE_COLORS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-label={t(option.label)}
              aria-pressed={color === option.value}
              onClick={() => setColor(option.value)}
              style={{ "--swatch": option.value } as React.CSSProperties}
            >
              <span aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
