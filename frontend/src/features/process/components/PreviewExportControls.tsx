import React, { memo, useCallback } from "react";
import { Spinner } from "@/components/Spinner";
import type { MessageKey } from "@/context/i18nMessages";
import { useDocumentScrollLock } from "@/hooks/useDocumentScrollLock";

export type PreviewTranslate = (
  key: MessageKey,
  params?: Record<string, string | number>,
) => string;

type ExportOption = {
  resolution: "720x1280" | "1080x1920" | "srt" | "txt" | "2160x3840";
  label: string;
  descriptionKey: MessageKey;
  loadingKey: MessageKey;
  testId: string;
  primary?: boolean;
};

const VIDEO_EXPORT_OPTIONS: ExportOption[] = [
  {
    resolution: "720x1280",
    label: "720p Fast",
    descriptionKey: "exportFastDesc",
    loadingKey: "exportRendering",
    testId: "download-720p-btn",
    primary: true,
  },
  {
    resolution: "1080x1920",
    label: "1080p",
    descriptionKey: "exportHdDesc",
    loadingKey: "exportRendering",
    testId: "download-1080p-btn",
  },
  {
    resolution: "2160x3840",
    label: "4K",
    descriptionKey: "export4kDesc",
    loadingKey: "exportMastering",
    testId: "download-4k-btn",
  },
];

const SUBTITLE_EXPORT_OPTIONS: ExportOption[] = [
  {
    resolution: "srt",
    label: "SRT",
    descriptionKey: "subtitleFileSrtDesc",
    loadingKey: "exportSaving",
    testId: "srt-btn",
  },
  {
    resolution: "txt",
    label: "TXT",
    descriptionKey: "subtitleFileTxtDesc",
    loadingKey: "exportSaving",
    testId: "txt-btn",
  },
];

const ExportAction = memo(
  ({
    option,
    isExporting,
    onExport,
    t,
  }: {
    option: ExportOption;
    isExporting: boolean;
    onExport: (resolution: string) => Promise<void>;
    t: PreviewTranslate;
  }) => (
    <button
      type="button"
      className={`editor-export-action ${option.primary ? "editor-export-action-primary" : ""}`}
      onClick={() => onExport(option.resolution)}
      disabled={isExporting}
      aria-busy={isExporting}
      data-testid={option.testId}
    >
      {isExporting ? (
        <span className="editor-export-loading">
          <Spinner className="h-4 w-4" />
          <span>{t(option.loadingKey)}</span>
        </span>
      ) : (
        <>
          <span className="editor-export-label">{option.label}</span>
          <span className="editor-export-description">
            {t(option.descriptionKey)}
          </span>
        </>
      )}
    </button>
  ),
);
ExportAction.displayName = "ExportAction";

const ExportGroup = memo(
  ({
    titleKey,
    formats,
    options,
    variant,
    testId,
    exportingResolutions,
    onExport,
    t,
  }: {
    titleKey: MessageKey;
    formats: string;
    options: ExportOption[];
    variant: "video" | "subtitles";
    testId: "video-export-group" | "subtitle-export-group";
    exportingResolutions: Record<string, boolean>;
    onExport: (resolution: string) => Promise<void>;
    t: PreviewTranslate;
  }) => {
    const headingId = `${testId}-title`;
    return (
      <section
        className="editor-export-group"
        aria-labelledby={headingId}
        data-testid={testId}
      >
        <div className="editor-export-group-heading">
          <h3 id={headingId}>{t(titleKey)}</h3>
          <span>{formats}</span>
        </div>
        <div className={`editor-export-grid editor-export-grid-${variant}`}>
          {options.map((option) => (
            <ExportAction
              key={option.resolution}
              option={option}
              isExporting={Boolean(exportingResolutions[option.resolution])}
              onExport={onExport}
              t={t}
            />
          ))}
        </div>
      </section>
    );
  },
);
ExportGroup.displayName = "ExportGroup";

function ExportMenuHeader({
  onClose,
  t,
}: {
  onClose: () => void;
  t: PreviewTranslate;
}) {
  return (
    <header className="editor-export-menu-header">
      <div>
        <h2 id="editor-export-menu-title">{t("stepExport")}</h2>
        <p id="editor-export-menu-description">{t("exportMenuDescription")}</p>
      </div>
      <button
        type="button"
        className="editor-export-menu-close"
        aria-label={t("closeLabel")}
        onClick={onClose}
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.8"
            d="M6 6l12 12M18 6L6 18"
          />
        </svg>
      </button>
    </header>
  );
}

function ExportMenuGroups({
  exportingResolutions,
  onExport,
  t,
}: {
  exportingResolutions: Record<string, boolean>;
  onExport: (resolution: string) => Promise<void>;
  t: PreviewTranslate;
}) {
  return (
    <div className="editor-export-groups" data-testid="editor-export-grid">
      <ExportGroup
        titleKey="exportVideoTitle"
        formats="MP4"
        options={VIDEO_EXPORT_OPTIONS}
        variant="video"
        testId="video-export-group"
        exportingResolutions={exportingResolutions}
        onExport={onExport}
        t={t}
      />
      <ExportGroup
        titleKey="exportSubtitlesTitle"
        formats="SRT · TXT"
        options={SUBTITLE_EXPORT_OPTIONS}
        variant="subtitles"
        testId="subtitle-export-group"
        exportingResolutions={exportingResolutions}
        onExport={onExport}
        t={t}
      />
    </div>
  );
}

interface ExportMenuProps {
  isOpen: boolean;
  onClose: () => void;
  restoreTriggerFocus: () => void;
  exportingResolutions: Record<string, boolean>;
  onExport: (resolution: string) => Promise<void>;
  exportFilenamePreview: string;
  exportError: string | null;
  t: PreviewTranslate;
}

export const ExportMenu = memo(function ExportMenu({
  isOpen,
  onClose,
  restoreTriggerFocus,
  exportingResolutions,
  onExport,
  exportFilenamePreview,
  exportError,
  t,
}: ExportMenuProps) {
  const menuRef = React.useRef<HTMLElement>(null);
  useDocumentScrollLock(isOpen);
  React.useEffect(() => {
    if (!isOpen) return;
    const focusFrame = window.requestAnimationFrame(() =>
      menuRef.current?.focus(),
    );
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleKeyDown);
      restoreTriggerFocus();
    };
  }, [isOpen, onClose, restoreTriggerFocus]);
  const handleExportSelection = useCallback(
    async (resolution: string) => {
      onClose();
      await onExport(resolution);
    },
    [onClose, onExport],
  );
  if (!isOpen) return null;
  return (
    <>
      <button
        type="button"
        className="editor-export-backdrop"
        aria-label={t("closeLabel")}
        tabIndex={-1}
        onClick={onClose}
      />
      <section
        ref={menuRef}
        id="editor-export-menu"
        className="editor-export-menu"
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby="editor-export-menu-title"
        aria-describedby="editor-export-menu-description"
        data-testid="editor-export-menu"
      >
        <span className="editor-export-menu-handle" aria-hidden="true" />
        <ExportMenuHeader onClose={onClose} t={t} />
        <ExportMenuGroups
          exportingResolutions={exportingResolutions}
          onExport={handleExportSelection}
          t={t}
        />
        <p
          className="editor-export-filename"
          data-testid="export-filename-preview"
        >
          <span>{t("exportFilenameLabel")}</span>
          <strong title={exportFilenamePreview}>{exportFilenamePreview}</strong>
        </p>
        <p className="editor-export-retention-note">
          <span aria-hidden="true">↻</span>
          {t("temporaryWorkspaceExportNote")}
        </p>
        {exportError && (
          <p className="editor-export-error" role="alert">
            {exportError}
          </p>
        )}
      </section>
    </>
  );
});
ExportMenu.displayName = "ExportMenu";

export const ExportProgress = memo(
  ({
    exportingResolutions,
    exportProgress,
    t,
  }: {
    exportingResolutions: Record<string, boolean>;
    exportProgress: Record<string, number | null>;
    t: PreviewTranslate;
  }) => {
    const resolution = Object.keys(exportingResolutions).find(
      (key) => exportingResolutions[key],
    );
    if (!resolution) return null;
    const progress = exportProgress[resolution];
    const numericProgress = typeof progress === "number" ? progress : undefined;
    return (
      <div className="editor-export-progress" data-testid="export-progress">
        <div className="editor-export-progress-copy">
          <span>{t("exportProgressLabel", { resolution })}</span>
          <strong>
            {numericProgress === undefined
              ? t("exportProgressPreparing")
              : `${numericProgress}%`}
          </strong>
        </div>
        <div
          className="editor-export-progress-track"
          role="progressbar"
          aria-label={t("exportProgressLabel", { resolution })}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={numericProgress}
        >
          <span
            className={numericProgress === undefined ? "is-indeterminate" : ""}
            style={
              numericProgress === undefined
                ? undefined
                : { width: `${numericProgress}%` }
            }
          />
        </div>
      </div>
    );
  },
);
ExportProgress.displayName = "ExportProgress";
