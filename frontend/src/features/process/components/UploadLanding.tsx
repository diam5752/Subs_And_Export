import type { DragEventHandler, ReactNode } from "react";
import { useI18n } from "@/context/I18nContext";
import { CaptionSample } from "./CaptionSample";
import styles from "./UploadLanding.module.css";

interface UploadLandingProps {
  isDragOver: boolean;
  disabled: boolean;
  maxSize: number;
  maxDuration: string;
  onChooseFile: () => void;
  onDragEnter: DragEventHandler<HTMLDivElement>;
  onDragLeave: DragEventHandler<HTMLDivElement>;
  onDragOver: DragEventHandler<HTMLDivElement>;
  onDrop: DragEventHandler<HTMLDivElement>;
  children: ReactNode;
}

function UploadPreviewIcon() {
  return (
    <span className="studio-upload-preview" aria-hidden="true">
      <svg viewBox="0 0 48 48" fill="none">
        <rect
          x="10"
          y="7"
          width="28"
          height="34"
          rx="6"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path d="M21 17.5 30 24l-9 6.5v-13Z" fill="currentColor" />
      </svg>
    </span>
  );
}

export function UploadLanding({ children, ...props }: UploadLandingProps) {
  const { t } = useI18n();
  return (
    <div className={styles.layout}>
      <div className={styles.primary}>
        <div
          onDragEnter={props.onDragEnter}
          onDragLeave={props.onDragLeave}
          onDragOver={props.onDragOver}
          onDrop={props.onDrop}
        >
          <button
            type="button"
            className={`studio-upload-zone ${props.isDragOver ? "studio-upload-zone-active" : ""}`}
            disabled={props.disabled}
            onClick={props.onChooseFile}
            aria-label={t("uploadDropTitle")}
            aria-describedby="upload-file-limits"
          >
            <UploadPreviewIcon />
            <span className={styles.uploadTitle}>{t("uploadStartTitle")}</span>
            <span className="studio-upload-cta">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              {props.isDragOver ? t("dropFileHere") : t("uploadDropTitle")}
            </span>
            <span className={styles.dropHint}>
              {props.isDragOver
                ? t("releaseToUpload")
                : t("uploadDropSubtitle")}
            </span>
            <span id="upload-file-limits" className={styles.fileLimits}>
              {t("uploadDropFootnote", {
                size: props.maxSize,
                duration: props.maxDuration,
              })}
            </span>
          </button>
        </div>
        {children}
      </div>
      <CaptionSample />
    </div>
  );
}
