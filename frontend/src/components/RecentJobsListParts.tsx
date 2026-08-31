import React from "react";
import type { JobResponse } from "@/lib/api";
import { JobListItem } from "./JobListItem";

export type RecentJobsTranslate = (
  key: string,
  params?: Record<string, string | number>,
) => string;

export function RecentJobsHeader({
  isLoading,
  hasJobs,
  selectionMode,
  onToggleSelectionMode,
  t,
}: {
  isLoading: boolean;
  hasJobs: boolean;
  selectionMode: boolean;
  onToggleSelectionMode: () => void;
  t: RecentJobsTranslate;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
      <div>
        <h3 className="text-lg font-semibold">
          {t("historyTitle") || "History"}
        </h3>
        <p className="text-xs text-[var(--muted)]">
          {t("historyExpiry") || "Items expire in 24 hours"}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {isLoading && (
          <span
            data-testid="jobs-loading"
            className="text-xs text-[var(--muted)]"
          >
            {t("refreshingLabel")}
          </span>
        )}
        {hasJobs && (
          <button
            onClick={onToggleSelectionMode}
            className={`min-h-11 text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              selectionMode
                ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                : "border-[var(--border)] hover:border-[var(--accent)]/50"
            }`}
          >
            {selectionMode
              ? t("cancelSelect") || "Cancel"
              : t("selectMode") || "Select"}
          </button>
        )}
      </div>
    </div>
  );
}

interface SelectionControlsProps {
  jobs: JobResponse[];
  selectedJobIds: Set<string>;
  confirmBatchDelete: boolean;
  isBatchDeleting: boolean;
  batchDeleteBtnRef: React.RefObject<HTMLButtonElement | null>;
  confirmBatchBtnRef: React.RefObject<HTMLButtonElement | null>;
  onSelectionChange: (ids: Set<string>) => void;
  onRequestDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => Promise<void>;
  t: RecentJobsTranslate;
}

function SelectAllControl({
  jobs,
  selectedJobIds,
  onSelectionChange,
  t,
}: Pick<
  SelectionControlsProps,
  "jobs" | "selectedJobIds" | "onSelectionChange" | "t"
>) {
  const allSelected = selectedJobIds.size === jobs.length;
  return (
    <label className="flex min-h-11 items-center gap-2 cursor-pointer text-sm">
      <input
        type="checkbox"
        checked={allSelected && jobs.length > 0}
        onChange={(event) =>
          onSelectionChange(
            event.target.checked
              ? new Set(jobs.map((job) => job.id))
              : new Set(),
          )
        }
        className="w-4 h-4 rounded border-[var(--border)] accent-[var(--accent)]"
      />
      {allSelected
        ? t("deselectAll") || "Deselect All"
        : t("selectAll") || "Select All"}
    </label>
  );
}

export function RecentJobsSelectionControls({
  jobs,
  selectedJobIds,
  confirmBatchDelete,
  isBatchDeleting,
  batchDeleteBtnRef,
  confirmBatchBtnRef,
  onSelectionChange,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
  t,
}: SelectionControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-3 mb-3 p-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]">
      <SelectAllControl
        jobs={jobs}
        selectedJobIds={selectedJobIds}
        onSelectionChange={onSelectionChange}
        t={t}
      />
      <span className="text-xs text-[var(--muted)]">
        {selectedJobIds.size} {t("selected") || "selected"}
      </span>
      <div className="flex-1" />
      {confirmBatchDelete ? (
        <BatchDeleteConfirmation
          selectedJobIds={selectedJobIds}
          isBatchDeleting={isBatchDeleting}
          confirmBatchBtnRef={confirmBatchBtnRef}
          onCancelDelete={onCancelDelete}
          onConfirmDelete={onConfirmDelete}
          t={t}
        />
      ) : (
        <button
          ref={batchDeleteBtnRef}
          onClick={onRequestDelete}
          disabled={selectedJobIds.size === 0}
          className="min-h-11 rounded border border-[var(--danger)] px-3 py-1.5 text-xs text-[var(--danger)] hover:bg-[var(--danger)]/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          🗑️ {t("deleteSelected") || "Delete Selected"} ({selectedJobIds.size})
        </button>
      )}
    </div>
  );
}

interface RecentJobsEmptyProps {
  t: RecentJobsTranslate;
}

export function RecentJobsEmpty(props: RecentJobsEmptyProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface-elevated)]/30 text-center animate-fade-in">
      <div className="mb-3 p-3 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)] text-[var(--muted)] opacity-70">
        <svg
          aria-hidden="true"
          className="w-6 h-6"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
      </div>
      <h4 className="text-sm font-semibold text-[var(--foreground)] mb-1">
        {props.t("noHistory") || "No history yet."}
      </h4>
      <p className="text-xs text-[var(--muted)] max-w-[200px]">
        {props.t("noRunsYet") || "Your processed videos will appear here."}
      </p>
    </div>
  );
}

interface RecentJobsRowsProps {
  jobs: JobResponse[];
  selectionMode: boolean;
  selectedJobIds: Set<string>;
  confirmDeleteId: string | null;
  deletingJobId: string | null;
  downloadingJobId: string | null;
  currentTimeMs: number;
  formatDate: (ts: number | string) => string;
  buildStaticUrl: (path?: string | null) => string | null;
  onToggleSelection: (id: string, isSelected: boolean) => void;
  onJobSelect: (job: JobResponse | null) => void;
  setShowPreview: (show: boolean) => void;
  setConfirmDeleteId: (id: string | null) => void;
  onDeleteConfirmed: (id: string) => Promise<void>;
  onDownload: (job: JobResponse) => Promise<void>;
  t: RecentJobsTranslate;
}

export function RecentJobsRows({
  jobs,
  selectionMode,
  selectedJobIds,
  confirmDeleteId,
  deletingJobId,
  downloadingJobId,
  currentTimeMs,
  formatDate,
  buildStaticUrl,
  onToggleSelection,
  onJobSelect,
  setShowPreview,
  setConfirmDeleteId,
  onDeleteConfirmed,
  onDownload,
  t,
}: RecentJobsRowsProps) {
  return (
    <div className="space-y-2">
      {jobs.map((job) => {
        const timestamp = (job.updated_at || job.created_at) * 1000;
        const expiryTimestamp = job.expires_at
          ? job.expires_at * 1000
          : timestamp + 86_400_000;
        return (
          <JobListItem
            key={job.id}
            job={job}
            selectionMode={selectionMode}
            isSelected={selectedJobIds.has(job.id)}
            isExpired={
              Boolean(job.result_data?.files_missing) ||
              currentTimeMs >= expiryTimestamp
            }
            publicUrl={buildStaticUrl(
              job.result_data?.public_url || job.result_data?.video_path,
            )}
            timestamp={timestamp}
            formatDate={formatDate}
            onToggleSelection={onToggleSelection}
            onJobSelect={onJobSelect}
            setShowPreview={setShowPreview}
            isConfirmingDelete={confirmDeleteId === job.id}
            isDeleting={deletingJobId === job.id}
            isDownloading={downloadingJobId === job.id}
            setConfirmDeleteId={setConfirmDeleteId}
            onDeleteConfirmed={onDeleteConfirmed}
            onDownload={onDownload}
            t={t}
          />
        );
      })}
    </div>
  );
}

export function RecentJobsPagination({
  currentPage,
  totalPages,
  totalJobs,
  pageSize,
  onNextPage,
  onPrevPage,
  t,
}: {
  currentPage: number;
  totalPages: number;
  totalJobs: number;
  pageSize: number;
  onNextPage: () => void;
  onPrevPage: () => void;
  t: RecentJobsTranslate;
}) {
  if (totalPages <= 1) return null;
  const start = (currentPage - 1) * pageSize + 1;
  const end = Math.min(currentPage * pageSize, totalJobs);
  const showing = t("paginationShowing")
    ? t("paginationShowing")
        .replace("{start}", String(start))
        .replace("{end}", String(end))
        .replace("{total}", String(totalJobs))
    : `Showing ${start}-${end} of ${totalJobs}`;
  return (
    <div className="flex items-center justify-center gap-4 mt-4 pt-4 border-t border-[var(--border)]">
      <button
        onClick={onPrevPage}
        disabled={currentPage <= 1}
        className="min-h-11 rounded-lg border border-[var(--border)] px-4 py-2 text-sm transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
      >
        ← {t("previousPage") || "Previous"}
      </button>
      <span className="text-sm text-[var(--muted)]">{showing}</span>
      <button
        onClick={onNextPage}
        disabled={currentPage >= totalPages}
        className="min-h-11 rounded-lg border border-[var(--border)] px-4 py-2 text-sm transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {t("nextPage") || "Next"} →
      </button>
    </div>
  );
}

type BatchDeleteConfirmationProps = Pick<
  SelectionControlsProps,
  | "selectedJobIds"
  | "isBatchDeleting"
  | "confirmBatchBtnRef"
  | "onCancelDelete"
  | "onConfirmDelete"
  | "t"
>;

function BatchDeleteConfirmation({
  selectedJobIds,
  isBatchDeleting,
  confirmBatchBtnRef,
  onCancelDelete,
  onConfirmDelete,
  t,
}: BatchDeleteConfirmationProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-[var(--danger)]">
        {t("deleteSelectedConfirm") || `Delete ${selectedJobIds.size} items?`}
      </span>
      <button
        ref={confirmBatchBtnRef}
        onClick={onConfirmDelete}
        disabled={isBatchDeleting}
        className="min-h-11 min-w-[60px] rounded bg-[var(--danger)] px-3 py-1.5 text-xs text-white hover:bg-[var(--danger)]/80 disabled:opacity-50"
      >
        {isBatchDeleting ? "..." : t("confirmDelete") || "Confirm"}
      </button>
      <button
        onClick={onCancelDelete}
        className="min-h-11 rounded border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-white/5"
      >
        {t("cancel") || "Cancel"}
      </button>
    </div>
  );
}
