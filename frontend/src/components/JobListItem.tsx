import React, { memo, useRef, useEffect } from 'react';
import { Spinner } from '@/components/Spinner';
import { JobResponse } from '@/lib/api';

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

function arePropsEqual(prev: JobListItemProps, next: JobListItemProps) {
    // Check if job essential data changed
    const jobChanged =
        prev.job.id !== next.job.id ||
        prev.job.status !== next.job.status ||
        prev.job.progress !== next.job.progress ||
        prev.job.updated_at !== next.job.updated_at ||
        prev.job.expires_at !== next.job.expires_at;

    if (jobChanged) return false;

    // Check other props
    return (
        prev.selectionMode === next.selectionMode &&
        prev.isSelected === next.isSelected &&
        prev.isExpired === next.isExpired &&
        prev.publicUrl === next.publicUrl &&
        prev.timestamp === next.timestamp &&
        prev.isConfirmingDelete === next.isConfirmingDelete &&
        prev.isDeleting === next.isDeleting &&
        prev.isDownloading === next.isDownloading &&
        // Functions (reference equality)
        prev.formatDate === next.formatDate &&
        prev.onToggleSelection === next.onToggleSelection &&
        prev.onJobSelect === next.onJobSelect &&
        prev.setShowPreview === next.setShowPreview &&
        prev.setConfirmDeleteId === next.setConfirmDeleteId &&
        prev.onDeleteConfirmed === next.onDeleteConfirmed &&
        prev.onDownload === next.onDownload &&
        prev.t === next.t
    );
}

export const JobListItem = memo(function JobListItem({
    job,
    selectionMode,
    isSelected,
    isExpired,
    publicUrl,
    timestamp,
    formatDate,
    onToggleSelection,
    onJobSelect,
    setShowPreview,
    isConfirmingDelete,
    isDeleting,
    isDownloading,
    setConfirmDeleteId,
    onDeleteConfirmed,
    onDownload,
    t
}: JobListItemProps) {
    const deleteBtnRef = useRef<HTMLButtonElement>(null);
    const confirmBtnRef = useRef<HTMLButtonElement>(null);
    const prevConfirmingRef = useRef(isConfirmingDelete);
    const wasCancelledRef = useRef(false);

    const displayFilename = job.result_data?.original_filename || job.id;
    const canDownload = Boolean(publicUrl);
    const remainingHours = job.expires_at
        ? Math.ceil(((job.expires_at * 1000) - Date.now()) / (60 * 60 * 1000))
        : null;

    useEffect(() => {
        // If entering confirmation mode
        if (isConfirmingDelete && !prevConfirmingRef.current) {
            // Focus the confirm button to continue the flow seamlessly
            requestAnimationFrame(() => {
                confirmBtnRef.current?.focus();
            });
        }

        // If exiting confirmation mode via cancel
        if (!isConfirmingDelete && prevConfirmingRef.current) {
            if (wasCancelledRef.current) {
                // Restore focus to the delete button that initiated it
                requestAnimationFrame(() => {
                    deleteBtnRef.current?.focus();
                });
                wasCancelledRef.current = false;
            }
        }

        prevConfirmingRef.current = isConfirmingDelete;
    }, [isConfirmingDelete]);

    const handleContainerClick = () => {
        if (selectionMode) {
            onToggleSelection(job.id, isSelected);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (!selectionMode) return;
        // Prevent triggering when interacting with children (though they should be non-interactive in selection mode)
        if (e.target !== e.currentTarget) return;

        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggleSelection(job.id, isSelected);
        }
    };

    const handleCheckboxChange = () => {
        // Handled by parent via onToggleSelection
    };

    return (
        <div
            onClick={handleContainerClick}
            onKeyDown={handleKeyDown}
            role={selectionMode ? 'button' : undefined}
            tabIndex={selectionMode ? 0 : undefined}
            aria-pressed={selectionMode ? isSelected : undefined}
            className={`flex flex-wrap sm:flex-nowrap items-center justify-between gap-3 p-3 rounded-lg border ${isSelected
                ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                : isExpired
                    ? 'border-[var(--border)]/30 bg-[var(--surface)] text-[var(--muted)]'
                    : 'border-[var(--border)] bg-[var(--surface-elevated)]'
                } transition-colors ${selectionMode ? 'cursor-pointer hover:bg-[var(--accent)]/5' : ''}`}
        >
            <div className="min-w-0 flex-1">
                <div className="font-semibold text-sm truncate">
                    {displayFilename}
                </div>
                <div className="text-xs text-[var(--muted)]">
                    {formatDate(timestamp)}
                </div>
                {!isExpired && remainingHours !== null && remainingHours > 0 && (
                    <div className="mt-0.5 text-[11px] font-medium text-[var(--muted)]">
                        {remainingHours <= 1
                            ? t('availableForLessThanHour')
                            : t('availableForHours', { hours: remainingHours })}
                    </div>
                )}
            </div>

            <div className="recent-job-actions flex w-full items-center justify-end gap-2 sm:w-auto sm:justify-start">
                {/* Checkbox for selection mode - Moved to right */}
                {selectionMode && (
                    <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={handleCheckboxChange}
                        className="w-4 h-4 rounded border-[var(--border)] accent-[var(--accent)] flex-shrink-0 cursor-pointer"
                        tabIndex={-1}
                        aria-hidden="true"
                    />
                )}
                {isExpired ? (
                    <span className="text-xs bg-[var(--surface)] border border-[var(--border)] px-2 py-1 rounded text-[var(--muted)]">
                        {t('expired') || 'Expired'}
                    </span>
                ) : (
                    <>
                        {job.status === 'completed' && canDownload && !selectionMode && (
                            <>
                                <button
                                    type="button"
                                    className="recent-job-action text-xs btn-primary min-h-11 px-3 py-1.5"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onDownload(job);
                                    }}
                                    disabled={isDownloading}
                                    aria-busy={isDownloading}
                                    aria-label={`${isDownloading
                                        ? (t('downloading') || 'Preparing download')
                                        : (t('download') || 'Download')} ${displayFilename}`}
                                >
                                    {isDownloading ? (
                                        <Spinner className="h-3.5 w-3.5 text-white" />
                                    ) : (
                                        t('download') || 'Download'
                                    )}
                                </button>
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onJobSelect(job);
                                        setShowPreview(true);
                                    }}
                                    className="recent-job-action text-xs btn-secondary min-h-11 px-3 py-1.5"
                                    aria-label={`${t('view') || 'View'} ${displayFilename}`}
                                >
                                    {t('view') || 'View'}
                                </button>
                            </>
                        )}
                        {/* Delete button - hide in selection mode */}
                        {!selectionMode && (
                            isConfirmingDelete ? (
                                <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                                    <button
                                        ref={confirmBtnRef}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onDeleteConfirmed(job.id);
                                        }}
                                        disabled={isDeleting}
                                        className="recent-job-icon-action flex h-11 min-w-11 items-center justify-center rounded bg-[var(--danger)] px-2 text-xs text-white hover:bg-[var(--danger)]/80 disabled:opacity-50"
                                        aria-label={isDeleting
                                            ? `${t('deleting') || 'Deleting'} ${displayFilename}`
                                            : `${t('confirmDelete') || 'Confirm delete'} ${displayFilename}`
                                        }
                                        aria-busy={isDeleting}
                                    >
                                        {isDeleting ? (
                                            <Spinner className="h-3.5 w-3.5 text-white" />
                                        ) : (
                                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                                            </svg>
                                        )}
                                    </button>
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            wasCancelledRef.current = true;
                                            setConfirmDeleteId(null);
                                        }}
                                        className="recent-job-icon-action flex h-11 min-w-11 items-center justify-center rounded border border-[var(--border)] px-2 text-xs hover:bg-white/5"
                                        aria-label={t('cancel') || 'Cancel'}
                                    >
                                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                                        </svg>
                                    </button>
                                </div>
                            ) : (
                                <button
                                    ref={deleteBtnRef}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setConfirmDeleteId(job.id);
                                    }}
                                    className="recent-job-icon-action flex h-11 min-w-11 items-center justify-center rounded border border-[var(--border)] px-2 text-xs transition-colors hover:border-[var(--danger)] hover:text-[var(--danger)]"
                                    title={t('deleteJob')}
                                    aria-label={`${t('deleteJob') || 'Delete job'} ${displayFilename}`}
                                >
                                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                    </svg>
                                </button>
                            )
                        )}
                    </>
                )}
            </div>
        </div>
    );
}, arePropsEqual);
