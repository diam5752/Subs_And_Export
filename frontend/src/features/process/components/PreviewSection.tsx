import React, { useCallback, useMemo } from "react";
import { useI18n } from "@/context/I18nContext";
import { buildSubtitleExportFilename } from "@/lib/exportFilename";
import { usePlaybackContext } from "../PlaybackContext";
import { useProcessContext } from "../ProcessContext";
import { PreviewSectionLayout } from "./PreviewSectionLayout";
import {
  usePreviewPlayerSettings,
  usePreviewSubtitleEditor,
  useLiveSubtitlePositioning,
} from "./usePreviewSectionConfig";

export function PreviewSection() {
  const { t } = useI18n();
  const {
    resultsRef,
    selectedJob,
    isProcessing,
    processedCues,
    playerRef,
    videoUrl,
    handleExport,
    exportingResolutions,
    exportProgress,
    exportError,
    activeSidebarTab,
    onReset,
    onJobSelect,
  } = useProcessContext();
  const { setCurrentTime } = usePlaybackContext();
  const [showNewVideoModal, setShowNewVideoModal] = React.useState(false);
  const [showExportMenu, setShowExportMenu] = React.useState(false);
  const playerSettings = usePreviewPlayerSettings();
  const subtitleEditor = usePreviewSubtitleEditor();
  const subtitlePositioning = useLiveSubtitlePositioning();
  const exportFilenamePreview = useMemo(
    () =>
      buildSubtitleExportFilename(
        selectedJob?.result_data?.original_filename,
        "mp4",
      ),
    [selectedJob?.result_data?.original_filename],
  );
  const handleNewVideoConfirm = useCallback(() => {
    onReset();
    onJobSelect(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [onJobSelect, onReset]);
  const handlePlayerTimeUpdate = useCallback(
    (time: number) => setCurrentTime(time),
    [setCurrentTime],
  );
  return (
    <PreviewSectionLayout
      ref={resultsRef}
      selectedJob={selectedJob}
      isProcessing={isProcessing}
      t={t}
      processedCues={processedCues}
      playerRef={playerRef}
      videoUrl={videoUrl}
      playerSettings={playerSettings}
      subtitleEditor={subtitleEditor}
      subtitlePositioning={subtitlePositioning}
      handlePlayerTimeUpdate={handlePlayerTimeUpdate}
      handleExport={handleExport}
      exportingResolutions={exportingResolutions}
      exportProgress={exportProgress}
      exportError={exportError}
      activeSidebarTab={activeSidebarTab}
      exportFilenamePreview={exportFilenamePreview}
      showNewVideoModal={showNewVideoModal}
      setShowNewVideoModal={setShowNewVideoModal}
      showExportMenu={showExportMenu}
      setShowExportMenu={setShowExportMenu}
      onNewVideoConfirm={handleNewVideoConfirm}
    />
  );
}
