import React, { memo } from "react";
import { PhoneFrame } from "@/components/PhoneFrame";
import {
  PreviewPlayer,
  type InlineSubtitleEditorConfig,
  type PreviewPlayerHandle,
} from "@/components/PreviewPlayer";
import { Spinner } from "@/components/Spinner";
import type { JobResponse } from "@/lib/api";
import { NewVideoConfirmModal } from "./NewVideoConfirmModal";
import {
  ExportMenu,
  ExportProgress,
  type PreviewTranslate,
} from "./PreviewExportControls";
import { Sidebar } from "./Sidebar";
import type { LiveSubtitlePositioning } from "./usePreviewSectionConfig";

interface PreviewSectionLayoutProps {
  selectedJob: JobResponse | null;
  isProcessing: boolean;
  t: PreviewTranslate;
  processedCues: React.ComponentProps<typeof PreviewPlayer>["cues"];
  playerRef: React.RefObject<PreviewPlayerHandle | null>;
  videoUrl: string | null;
  playerSettings: React.ComponentProps<typeof PreviewPlayer>["settings"];
  subtitleEditor: InlineSubtitleEditorConfig;
  subtitlePositioning: LiveSubtitlePositioning;
  handlePlayerTimeUpdate: (time: number) => void;
  handleExport: (resolution: string) => Promise<void>;
  exportingResolutions: Record<string, boolean>;
  exportProgress: Record<string, number | null>;
  exportError: string | null;
  activeSidebarTab: "transcript" | "styles";
  exportFilenamePreview: string;
  showNewVideoModal: boolean;
  setShowNewVideoModal: React.Dispatch<React.SetStateAction<boolean>>;
  showExportMenu: boolean;
  setShowExportMenu: React.Dispatch<React.SetStateAction<boolean>>;
  onNewVideoConfirm: () => void;
}

type PreviewContentProps = Omit<PreviewSectionLayoutProps, "playerRef">;

const SubtitlePositionScopeToggle = memo(
  ({
    positioning,
    t,
  }: {
    positioning: LiveSubtitlePositioning;
    t: PreviewTranslate;
  }) => {
    const hintId = React.useId();
    const currentCueOnly = positioning.scope === "cue";
    return (
      <div
        className="subtitle-position-scope-control"
        data-scope={positioning.scope}
        data-testid="subtitle-position-scope"
      >
        <button
          type="button"
          role="switch"
          aria-checked={currentCueOnly}
          aria-describedby={hintId}
          aria-label={t("subtitlePositionScopeLabel")}
          disabled={positioning.disabled}
          onClick={() =>
            positioning.onScopeChange(currentCueOnly ? "all" : "cue")
          }
          className="subtitle-position-scope-toggle"
        >
          <span aria-hidden="true" className="subtitle-position-scope-switch" />
          <span className="subtitle-position-scope-label">
            {t("subtitlePositionScopeLabel")}
          </span>
        </button>
        <p id={hintId} className="subtitle-position-scope-hint">
          {t(
            currentCueOnly
              ? "subtitleDragHandleLabel"
              : "subtitleDragAllHandleLabel",
          )}
        </p>
      </div>
    );
  },
);
SubtitlePositionScopeToggle.displayName = "SubtitlePositionScopeToggle";

function PreviewEmptyState({ t }: { t: PreviewTranslate }) {
  return (
    <div className="editor-empty-state">
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.5"
          d="M15 10l4.5-2.25A1 1 0 0121 8.65v6.7a1 1 0 01-1.5.9L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
        />
      </svg>
      <p>{t("resultPreviewTitle")}</p>
      <span>{t("resultPreviewDescription")}</span>
    </div>
  );
}

function PreviewPlaceholder({ t }: { t: PreviewTranslate }) {
  return (
    <div className="editor-preview-placeholder">
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
        <path d="M8.5 6.9a1 1 0 011.52-.85l7.3 4.6a1 1 0 010 1.7l-7.3 4.6a1 1 0 01-1.52-.85V6.9z" />
      </svg>
      <span>{t("clickToPreview")}</span>
    </div>
  );
}

function PositionScopeOverlay({
  positioning,
  t,
}: {
  positioning: LiveSubtitlePositioning;
  t: PreviewTranslate;
}) {
  return (
    <div className="subtitle-position-scope-overlay">
      <SubtitlePositionScopeToggle positioning={positioning} t={t} />
    </div>
  );
}

function ReadyActions(props: PreviewContentProps) {
  const exporting = Object.values(props.exportingResolutions).some(Boolean);
  const exportTriggerRef = React.useRef<HTMLButtonElement>(null);
  const restoreTriggerFocus = React.useCallback(
    () => exportTriggerRef.current?.focus(),
    [],
  );
  return (
    <div className="editor-ready-actions">
      <button
        type="button"
        onClick={() => {
          props.setShowExportMenu(false);
          props.setShowNewVideoModal(true);
        }}
        className="editor-new-video"
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
            strokeWidth="2"
            d="M12 5v14m7-7H5"
          />
        </svg>
        <span>{props.t("newVideoButton")}</span>
      </button>
      <button
        ref={exportTriggerRef}
        type="button"
        className="editor-export-trigger"
        aria-haspopup="dialog"
        aria-expanded={props.showExportMenu}
        aria-controls="editor-export-menu"
        aria-busy={exporting}
        disabled={exporting}
        onClick={() => props.setShowExportMenu((open) => !open)}
      >
        {exporting ? (
          <Spinner className="h-4 w-4" />
        ) : (
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
              d="M12 3v12m0 0l-4-4m4 4l4-4M5 19h14"
            />
          </svg>
        )}
        <span>{props.t("exportMenuButton")}</span>
      </button>
      <ExportMenu
        isOpen={props.showExportMenu}
        onClose={() => props.setShowExportMenu(false)}
        restoreTriggerFocus={restoreTriggerFocus}
        exportingResolutions={props.exportingResolutions}
        onExport={props.handleExport}
        exportFilenamePreview={props.exportFilenamePreview}
        exportError={props.exportError}
        t={props.t}
      />
    </div>
  );
}

function PreviewPlayerPanel({
  playerRef,
  ...props
}: PreviewSectionLayoutProps) {
  const initialTime = props.processedCues?.length
    ? props.processedCues[0].start
    : 0;
  return (
    <section
      className="editor-preview-panel"
      data-testid="editor-preview-panel"
      aria-label={props.t("previewWindowLabel")}
    >
      <div className="editor-preview-stage">
        <div className="editor-phone" data-testid="editor-phone">
          <PhoneFrame className="h-full w-full" showSocialOverlays={false}>
            {props.videoUrl ? (
              <>
                <PreviewPlayer
                  ref={playerRef}
                  videoUrl={props.videoUrl}
                  cues={props.processedCues || []}
                  settings={props.playerSettings}
                  subtitleEditor={props.subtitleEditor}
                  subtitleTransformControls={
                    props.subtitlePositioning.transformControls
                  }
                  onTimeUpdate={props.handlePlayerTimeUpdate}
                  playbackToggleLabel={props.t("previewVideoToggle")}
                  initialTime={initialTime}
                />
                {props.processedCues.length > 0 && (
                  <PositionScopeOverlay
                    positioning={props.subtitlePositioning}
                    t={props.t}
                  />
                )}
              </>
            ) : (
              <PreviewPlaceholder t={props.t} />
            )}
          </PhoneFrame>
        </div>
      </div>
    </section>
  );
}

function CompletedEditor({ playerRef, ...props }: PreviewSectionLayoutProps) {
  if (props.isProcessing) return null;
  return (
    <div
      className="editor-product animate-fade-in"
      data-testid="completed-editor"
    >
      <div
        id="editor-workspace"
        className={`editor-workspace ${props.activeSidebarTab === "styles" ? "editor-workspace-style-mode" : ""}`}
        data-editor-mode={props.activeSidebarTab}
        data-testid="editor-workspace"
      >
        <PreviewPlayerPanel playerRef={playerRef} {...props} />
        <Sidebar />
      </div>
    </div>
  );
}

function PreviewReadyState({ playerRef, ...props }: PreviewSectionLayoutProps) {
  return (
    <>
      <ReadyActions {...props} />
      <ExportProgress
        exportingResolutions={props.exportingResolutions}
        exportProgress={props.exportProgress}
        t={props.t}
      />
      <CompletedEditor playerRef={playerRef} {...props} />
    </>
  );
}

export const PreviewSectionLayout = memo(
  React.forwardRef<HTMLDivElement, PreviewSectionLayoutProps>(
    ({ playerRef, ...props }, resultsRef) => (
      <div
        id="preview-section"
        className={`card editor-section ${!props.selectedJob && !props.isProcessing ? "opacity-50 grayscale" : ""}`}
        ref={resultsRef}
      >
        <div id="editor-section-content">
          {!props.selectedJob || props.selectedJob.status !== "completed" ? (
            <PreviewEmptyState t={props.t} />
          ) : (
            <PreviewReadyState playerRef={playerRef} {...props} />
          )}
          <NewVideoConfirmModal
            isOpen={props.showNewVideoModal}
            onClose={() => props.setShowNewVideoModal(false)}
            onConfirm={props.onNewVideoConfirm}
          />
        </div>
      </div>
    ),
  ),
);
PreviewSectionLayout.displayName = "PreviewSectionLayout";
