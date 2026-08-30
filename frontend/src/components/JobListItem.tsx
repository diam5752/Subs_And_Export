import React, { memo, useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/Spinner";
import { JobResponse } from "@/lib/api";

interface JobListItemProps {
  job: JobResponse;
  selectionMode: boolean;
  isSelected: boolean;
  isExpired: boolean;
  publicUrl: string | null;
  timestamp: number;
  formatDate: (ts: number | string) => string;
  onToggleSelection: (id: string, isSelected: boolean) => void;
  onJobSelect: (job: JobResponse | null) => void;
  setShowPreview: (show: boolean) => void;
  isConfirmingDelete: boolean;
  isDeleting: boolean;
  isDownloading: boolean;
  setConfirmDeleteId: (id: string | null) => void;
  onDeleteConfirmed: (id: string) => void;
  onDownload: (job: JobResponse) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

type Translate = JobListItemProps["t"];

function arePropsEqual(previous: JobListItemProps, next: JobListItemProps) {
  const jobChanged =
    previous.job.id !== next.job.id ||
    previous.job.status !== next.job.status ||
    previous.job.progress !== next.job.progress ||
    previous.job.updated_at !== next.job.updated_at ||
    previous.job.expires_at !== next.job.expires_at;
  if (jobChanged) return false;
  return (
    previous.selectionMode === next.selectionMode &&
    previous.isSelected === next.isSelected &&
    previous.isExpired === next.isExpired &&
    previous.publicUrl === next.publicUrl &&
    previous.timestamp === next.timestamp &&
    previous.isConfirmingDelete === next.isConfirmingDelete &&
    previous.isDeleting === next.isDeleting &&
    previous.isDownloading === next.isDownloading &&
    previous.formatDate === next.formatDate &&
    previous.onToggleSelection === next.onToggleSelection &&
    previous.onJobSelect === next.onJobSelect &&
    previous.setShowPreview === next.setShowPreview &&
    previous.setConfirmDeleteId === next.setConfirmDeleteId &&
    previous.onDeleteConfirmed === next.onDeleteConfirmed &&
    previous.onDownload === next.onDownload &&
    previous.t === next.t
  );
}

function jobContainerClassName(
  isSelected: boolean,
  isExpired: boolean,
  selectionMode: boolean,
) {
  let stateClassName = "border-[var(--border)] bg-[var(--surface-elevated)]";
  if (isSelected) {
    stateClassName = "border-[var(--accent)] bg-[var(--accent)]/5";
  } else if (isExpired) {
    stateClassName =
      "border-[var(--border)]/30 bg-[var(--surface)] text-[var(--muted)]";
  }
  const selectionClassName = selectionMode
    ? "cursor-pointer hover:bg-[var(--accent)]/5"
    : "";
  return `flex flex-wrap sm:flex-nowrap items-center justify-between gap-3 p-3 rounded-lg border ${stateClassName} transition-colors ${selectionClassName}`;
}

function RemainingAvailability({
  isExpired,
  remainingHours,
  t,
}: {
  isExpired: boolean;
  remainingHours: number | null;
  t: Translate;
}) {
  if (isExpired || remainingHours === null || remainingHours <= 0) return null;
  const label =
    remainingHours <= 1
      ? t("availableForLessThanHour")
      : t("availableForHours", { hours: remainingHours });
  return (
    <div className="mt-0.5 text-[11px] font-medium text-[var(--muted)]">
      {label}
    </div>
  );
}

function CompletedJobActions({
  job,
  displayFilename,
  isDownloading,
  onDownload,
  onJobSelect,
  setShowPreview,
  t,
}: {
  job: JobResponse;
  displayFilename: string;
  isDownloading: boolean;
  onDownload: (job: JobResponse) => void;
  onJobSelect: (job: JobResponse | null) => void;
  setShowPreview: (show: boolean) => void;
  t: Translate;
}) {
  return (
    <>
      <button
        type="button"
        className="recent-job-action text-xs btn-primary min-h-11 px-3 py-1.5"
        onClick={(event) => {
          event.stopPropagation();
          onDownload(job);
        }}
        disabled={isDownloading}
        aria-busy={isDownloading}
        aria-label={`${
          isDownloading
            ? t("downloading") || "Preparing download"
            : t("download") || "Download"
        } ${displayFilename}`}
      >
        {isDownloading ? (
          <Spinner className="h-3.5 w-3.5 text-white" />
        ) : (
          t("download") || "Download"
        )}
      </button>
      <button
        onClick={(event) => {
          event.stopPropagation();
          onJobSelect(job);
          setShowPreview(true);
        }}
        className="recent-job-action text-xs btn-secondary min-h-11 px-3 py-1.5"
        aria-label={`${t("view") || "View"} ${displayFilename}`}
      >
        {t("view") || "View"}
      </button>
    </>
  );
}

function ConfirmDeleteActions({
  jobId,
  displayFilename,
  isDeleting,
  confirmButtonRef,
  wasCancelledRef,
  setConfirmDeleteId,
  onDeleteConfirmed,
  t,
}: {
  jobId: string;
  displayFilename: string;
  isDeleting: boolean;
  confirmButtonRef: React.RefObject<HTMLButtonElement | null>;
  wasCancelledRef: React.MutableRefObject<boolean>;
  setConfirmDeleteId: (id: string | null) => void;
  onDeleteConfirmed: (id: string) => void;
  t: Translate;
}) {
  return (
    <div
      className="flex items-center gap-1"
      onClick={(event) => event.stopPropagation()}
    >
      <button
        ref={confirmButtonRef}
        onClick={(event) => {
          event.stopPropagation();
          onDeleteConfirmed(jobId);
        }}
        disabled={isDeleting}
        className="recent-job-icon-action flex h-11 min-w-11 items-center justify-center rounded bg-[var(--danger)] px-2 text-xs text-white hover:bg-[var(--danger)]/80 disabled:opacity-50"
        aria-label={
          isDeleting
            ? `${t("deleting") || "Deleting"} ${displayFilename}`
            : `${t("confirmDelete") || "Confirm delete"} ${displayFilename}`
        }
        aria-busy={isDeleting}
      >
        {isDeleting ? (
          <Spinner className="h-3.5 w-3.5 text-white" />
        ) : (
          <svg
            className="w-3.5 h-3.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2.5}
              d="M5 13l4 4L19 7"
            />
          </svg>
        )}
      </button>
      <button
        onClick={(event) => {
          event.stopPropagation();
          wasCancelledRef.current = true;
          setConfirmDeleteId(null);
        }}
        className="recent-job-icon-action flex h-11 min-w-11 items-center justify-center rounded border border-[var(--border)] px-2 text-xs hover:bg-white/5"
        aria-label={t("cancel") || "Cancel"}
      >
        <svg
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2.5}
            d="M6 18L18 6M6 6l12 12"
          />
        </svg>
      </button>
    </div>
  );
}

function DeleteJobAction({
  jobId,
  displayFilename,
  isConfirmingDelete,
  isDeleting,
  deleteButtonRef,
  confirmButtonRef,
  wasCancelledRef,
  setConfirmDeleteId,
  onDeleteConfirmed,
  t,
}: {
  jobId: string;
  displayFilename: string;
  isConfirmingDelete: boolean;
  isDeleting: boolean;
  deleteButtonRef: React.RefObject<HTMLButtonElement | null>;
  confirmButtonRef: React.RefObject<HTMLButtonElement | null>;
  wasCancelledRef: React.MutableRefObject<boolean>;
  setConfirmDeleteId: (id: string | null) => void;
  onDeleteConfirmed: (id: string) => void;
  t: Translate;
}) {
  if (isConfirmingDelete) {
    return (
      <ConfirmDeleteActions
        jobId={jobId}
        displayFilename={displayFilename}
        isDeleting={isDeleting}
        confirmButtonRef={confirmButtonRef}
        wasCancelledRef={wasCancelledRef}
        setConfirmDeleteId={setConfirmDeleteId}
        onDeleteConfirmed={onDeleteConfirmed}
        t={t}
      />
    );
  }
  return (
    <button
      ref={deleteButtonRef}
      onClick={(event) => {
        event.stopPropagation();
        setConfirmDeleteId(jobId);
      }}
      className="recent-job-icon-action flex h-11 min-w-11 items-center justify-center rounded border border-[var(--border)] px-2 text-xs transition-colors hover:border-[var(--danger)] hover:text-[var(--danger)]"
      title={t("deleteJob")}
      aria-label={`${t("deleteJob") || "Delete job"} ${displayFilename}`}
    >
      <svg
        className="w-3.5 h-3.5"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
        />
      </svg>
    </button>
  );
}

function JobActions({
  job,
  displayFilename,
  selectionMode,
  isSelected,
  isExpired,
  canDownload,
  isConfirmingDelete,
  isDeleting,
  isDownloading,
  deleteButtonRef,
  confirmButtonRef,
  wasCancelledRef,
  setConfirmDeleteId,
  onDeleteConfirmed,
  onDownload,
  onJobSelect,
  setShowPreview,
  t,
}: JobListItemProps & {
  displayFilename: string;
  canDownload: boolean;
  deleteButtonRef: React.RefObject<HTMLButtonElement | null>;
  confirmButtonRef: React.RefObject<HTMLButtonElement | null>;
  wasCancelledRef: React.MutableRefObject<boolean>;
}) {
  if (isExpired) {
    return (
      <span className="text-xs bg-[var(--surface)] border border-[var(--border)] px-2 py-1 rounded text-[var(--muted)]">
        {t("expired") || "Expired"}
      </span>
    );
  }
  const showCompletedActions =
    job.status === "completed" && canDownload && !selectionMode;
  return (
    <>
      {selectionMode && (
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => undefined}
          className="w-4 h-4 rounded border-[var(--border)] accent-[var(--accent)] flex-shrink-0 cursor-pointer"
          tabIndex={-1}
          aria-hidden="true"
        />
      )}
      {showCompletedActions && (
        <CompletedJobActions
          job={job}
          displayFilename={displayFilename}
          isDownloading={isDownloading}
          onDownload={onDownload}
          onJobSelect={onJobSelect}
          setShowPreview={setShowPreview}
          t={t}
        />
      )}
      {!selectionMode && (
        <DeleteJobAction
          jobId={job.id}
          displayFilename={displayFilename}
          isConfirmingDelete={isConfirmingDelete}
          isDeleting={isDeleting}
          deleteButtonRef={deleteButtonRef}
          confirmButtonRef={confirmButtonRef}
          wasCancelledRef={wasCancelledRef}
          setConfirmDeleteId={setConfirmDeleteId}
          onDeleteConfirmed={onDeleteConfirmed}
          t={t}
        />
      )}
    </>
  );
}

export const JobListItem = memo(function JobListItem(props: JobListItemProps) {
  const {
    job,
    selectionMode,
    isSelected,
    isExpired,
    publicUrl,
    timestamp,
    formatDate,
    onToggleSelection,
    isConfirmingDelete,
    t,
  } = props;
  const deleteButtonRef = useRef<HTMLButtonElement>(null);
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  const previousConfirmingRef = useRef(isConfirmingDelete);
  const wasCancelledRef = useRef(false);
  const [renderedAt] = useState(Date.now);
  const displayFilename = job.result_data?.original_filename || job.id;
  const remainingHours = job.expires_at
    ? Math.ceil((job.expires_at * 1000 - renderedAt) / (60 * 60 * 1000))
    : null;

  useEffect(() => {
    if (isConfirmingDelete && !previousConfirmingRef.current) {
      requestAnimationFrame(() => confirmButtonRef.current?.focus());
    }
    if (
      !isConfirmingDelete &&
      previousConfirmingRef.current &&
      wasCancelledRef.current
    ) {
      requestAnimationFrame(() => deleteButtonRef.current?.focus());
      wasCancelledRef.current = false;
    }
    previousConfirmingRef.current = isConfirmingDelete;
  }, [isConfirmingDelete]);

  const handleContainerClick = () => {
    if (selectionMode) onToggleSelection(job.id, isSelected);
  };
  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (!selectionMode || event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onToggleSelection(job.id, isSelected);
  };

  return (
    <div
      onClick={handleContainerClick}
      onKeyDown={handleKeyDown}
      role={selectionMode ? "button" : undefined}
      tabIndex={selectionMode ? 0 : undefined}
      aria-pressed={selectionMode ? isSelected : undefined}
      className={jobContainerClassName(isSelected, isExpired, selectionMode)}
    >
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-sm truncate">{displayFilename}</div>
        <div className="text-xs text-[var(--muted)]">
          {formatDate(timestamp)}
        </div>
        <RemainingAvailability
          isExpired={isExpired}
          remainingHours={remainingHours}
          t={t}
        />
      </div>
      <div className="recent-job-actions flex w-full items-center justify-end gap-2 sm:w-auto sm:justify-start">
        <JobActions
          {...props}
          displayFilename={displayFilename}
          canDownload={Boolean(publicUrl)}
          deleteButtonRef={deleteButtonRef}
          confirmButtonRef={confirmButtonRef}
          wasCancelledRef={wasCancelledRef}
        />
      </div>
    </div>
  );
}, arePropsEqual);
