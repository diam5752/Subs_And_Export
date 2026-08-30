import React, { memo, useCallback, useEffect, useRef, useState } from "react";
import { api, type JobResponse } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { buildSubtitleExportFilename } from "@/lib/exportFilename";
import { downloadArtifactWithGrant } from "@/lib/artifactDownload";
import {
  RecentJobsEmpty,
  RecentJobsHeader,
  RecentJobsPagination,
  RecentJobsRows,
  RecentJobsSelectionControls,
  type RecentJobsTranslate,
} from "./RecentJobsListParts";

interface RecentJobsListProps {
  jobs: JobResponse[];
  isLoading: boolean;
  onJobSelect: (job: JobResponse | null) => void;
  selectedJobId: string | undefined;
  onRefreshJobs: () => Promise<void>;
  formatDate: (ts: number | string) => string;
  buildStaticUrl: (path?: string | null) => string | null;
  setShowPreview: (show: boolean) => void;
  currentPage: number;
  totalPages: number;
  onNextPage: () => void;
  onPrevPage: () => void;
  totalJobs: number;
  pageSize: number;
}

function useCurrentTimeMs() {
  const [currentTimeMs, setCurrentTimeMs] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(
      () => setCurrentTimeMs(Date.now()),
      30_000,
    );
    return () => window.clearInterval(timer);
  }, []);
  return currentTimeMs;
}

export const RecentJobsList = memo(function RecentJobsList({
  jobs,
  isLoading,
  onJobSelect,
  selectedJobId,
  onRefreshJobs,
  formatDate,
  buildStaticUrl,
  setShowPreview,
  currentPage,
  totalPages,
  onNextPage,
  onPrevPage,
  totalJobs,
  pageSize,
}: RecentJobsListProps) {
  const { t } = useI18n();
  const translate = t as RecentJobsTranslate;
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set());
  const [isBatchDeleting, setIsBatchDeleting] = useState(false);
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [downloadingJobId, setDownloadingJobId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const batchDeleteBtnRef = useRef<HTMLButtonElement>(null);
  const confirmBatchBtnRef = useRef<HTMLButtonElement>(null);
  const prevBatchConfirmingRef = useRef(confirmBatchDelete);
  const selectedJobIdRef = useRef(selectedJobId);
  const currentTimeMs = useCurrentTimeMs();

  useEffect(() => {
    selectedJobIdRef.current = selectedJobId;
  }, [selectedJobId]);

  useEffect(() => {
    const entering = confirmBatchDelete && !prevBatchConfirmingRef.current;
    const exiting = !confirmBatchDelete && prevBatchConfirmingRef.current;
    if (entering || exiting) {
      requestAnimationFrame(() => {
        (entering ? confirmBatchBtnRef : batchDeleteBtnRef).current?.focus();
      });
    }
    prevBatchConfirmingRef.current = confirmBatchDelete;
  }, [confirmBatchDelete]);

  const handleDeleteJob = useCallback(
    async (jobId: string) => {
      setDeletingJobId(jobId);
      try {
        await api.deleteJob(jobId);
        if (selectedJobIdRef.current === jobId) {
          onJobSelect(null);
          setShowPreview(false);
        }
        setConfirmDeleteId(null);
        await onRefreshJobs();
      } catch (error) {
        console.error("Delete failed:", error);
      } finally {
        setDeletingJobId(null);
      }
    },
    [onJobSelect, onRefreshJobs, setShowPreview],
  );

  const handleToggleSelection = useCallback(
    (id: string, isSelected: boolean) => {
      setSelectedJobIds((previous) => {
        const next = new Set(previous);
        if (isSelected) next.delete(id);
        else next.add(id);
        return next;
      });
    },
    [],
  );

  const handleDownloadJob = useCallback(
    async (job: JobResponse) => {
      const artifactPath =
        job.result_data?.public_url || job.result_data?.video_path;
      if (!artifactPath) {
        setDownloadError(
          t("downloadError") || "The secure download could not be prepared.",
        );
        return;
      }
      setDownloadError(null);
      setDownloadingJobId(job.id);
      try {
        await downloadArtifactWithGrant(
          job.id,
          artifactPath,
          buildSubtitleExportFilename(
            job.result_data?.original_filename,
            "mp4",
          ),
          buildStaticUrl,
        );
      } catch (error) {
        console.error("History download failed:", error);
        setDownloadError(
          t("downloadError") || "The secure download could not be prepared.",
        );
      } finally {
        setDownloadingJobId(null);
      }
    },
    [buildStaticUrl, t],
  );

  const handleBatchDelete = useCallback(async () => {
    setIsBatchDeleting(true);
    try {
      await api.deleteJobs(Array.from(selectedJobIds));
      if (selectedJobId && selectedJobIds.has(selectedJobId)) {
        onJobSelect(null);
        setShowPreview(false);
      }
      setSelectedJobIds(new Set());
      setConfirmBatchDelete(false);
      setSelectionMode(false);
      await onRefreshJobs();
    } catch (error) {
      console.error("Batch delete failed:", error);
    } finally {
      setIsBatchDeleting(false);
    }
  }, [
    onJobSelect,
    onRefreshJobs,
    selectedJobId,
    selectedJobIds,
    setShowPreview,
  ]);

  const toggleSelectionMode = useCallback(() => {
    setSelectionMode((enabled) => {
      if (enabled) {
        setSelectedJobIds(new Set());
        setConfirmBatchDelete(false);
      }
      return !enabled;
    });
  }, []);

  return (
    <div className="recent-jobs-list card mt-6 border-none bg-transparent shadow-none p-0">
      <RecentJobsHeader
        isLoading={isLoading}
        hasJobs={jobs.length > 0}
        selectionMode={selectionMode}
        onToggleSelectionMode={toggleSelectionMode}
        t={translate}
      />
      {selectionMode && jobs.length > 0 && (
        <RecentJobsSelectionControls
          jobs={jobs}
          selectedJobIds={selectedJobIds}
          confirmBatchDelete={confirmBatchDelete}
          isBatchDeleting={isBatchDeleting}
          batchDeleteBtnRef={batchDeleteBtnRef}
          confirmBatchBtnRef={confirmBatchBtnRef}
          onSelectionChange={setSelectedJobIds}
          onRequestDelete={() => setConfirmBatchDelete(true)}
          onCancelDelete={() => setConfirmBatchDelete(false)}
          onConfirmDelete={handleBatchDelete}
          t={translate}
        />
      )}
      {jobs.length === 0 && <RecentJobsEmpty t={translate} />}
      {downloadError && (
        <p
          className="rounded-lg border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-xs text-[var(--danger)]"
          role="alert"
        >
          {downloadError}
        </p>
      )}
      <RecentJobsRows
        jobs={jobs}
        selectionMode={selectionMode}
        selectedJobIds={selectedJobIds}
        confirmDeleteId={confirmDeleteId}
        deletingJobId={deletingJobId}
        downloadingJobId={downloadingJobId}
        currentTimeMs={currentTimeMs}
        formatDate={formatDate}
        buildStaticUrl={buildStaticUrl}
        onToggleSelection={handleToggleSelection}
        onJobSelect={onJobSelect}
        setShowPreview={setShowPreview}
        setConfirmDeleteId={setConfirmDeleteId}
        onDeleteConfirmed={handleDeleteJob}
        onDownload={handleDownloadJob}
        t={translate}
      />
      <RecentJobsPagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalJobs={totalJobs}
        pageSize={pageSize}
        onNextPage={onNextPage}
        onPrevPage={onPrevPage}
        t={translate}
      />
    </div>
  );
});
