import React, { memo, useRef, useEffect, useState } from 'react';
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
    setConfirmDeleteId: (id: string | null) => void;
    onDeleteConfirmed: (id: string) => void;
    t: (key: string) => string;
}

function arePropsEqual(prev: JobListItemProps, next: JobListItemProps) {
    // Check if job essential data changed
    const jobChanged =
        prev.job.id !== next.job.id ||
        prev.job.status !== next.job.status ||
        prev.job.progress !== next.job.progress ||
        prev.job.updated_at !== next.job.updated_at;

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
        // Functions (reference equality)
        prev.formatDate === next.formatDate &&
        prev.onToggleSelection === next.onToggleSelection &&
        prev.onJobSelect === next.onJobSelect &&
        prev.setShowPreview === next.setShowPreview &&
        prev.setConfirmDeleteId === next.setConfirmDeleteId &&
        prev.onDeleteConfirmed === next.onDeleteConfirmed &&
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
    setConfirmDeleteId,
    onDeleteConfirmed,
    t
}: JobListItemProps) {
    const deleteBtnRef = useRef<HTMLButtonElement>(null);
    const confirmBtnRef = useRef<HTMLButtonElement>(null);
    const prevConfirmingRef = useRef(isConfirmingDelete);
    const wasCancelledRef = useRef(false);
    const [isCopied, setIsCopied] = useState(false);

    const displayFilename = job.result_data?.original_filename || job.id;

    useEffect(() => {
        if (isCopied) {
            const timer = setTimeout(() => setIsCopied(false), 2000);
            return () => clearTimeout(timer);
        }
    }, [isCopied]);

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

    const handleCopyLink = async (e: React.MouseEvent) => {
        e.stopPropagation();
        if (!publicUrl) return;
        try {
            await navigator.clipboard.writeText(publicUrl);
            setIsCopied(true);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
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
            </div>

            <div className="flex items-center gap-2">
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
                        {job.status === 'completed' && publicUrl && !selectionMode && (
                            <>
                                <button
                                    onClick={handleCopyLink}
                                    className="text-xs px-2 py-1.5 rounded border border-[var(--border)] hover:bg-[var(--surface-elevated)] hover:text-[var(--accent)] transition-all flex items-center gap-1.5 h-auto min-w-[28px] justify-center"
                                    title={t('copyLink') || 'Copy Link'}
                                    aria-label={isCopied ? (t('copied') || 'Copied') : (t('copyLink') || 'Copy Link')}
                                >
                                    {isCopied ? (
                                        <svg className="w-3.5 h-3.5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                                        </svg>
                                    ) : (
                                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                                        </svg>
                                    )}
                                </button>
                                <a
                                    className="text-xs btn-primary py-1.5 px-3 h-auto"
                                    href={publicUrl}
                                    download={job.result_data?.original_filename || 'processed.mp4'}
                                    onClick={(e) => e.stopPropagation()}
                                    aria-label={`${t('download') || 'Download'} ${displayFilename}`}
                                >
                                    {t('download') || 'Download'}
                                </a>
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onJobSelect(job);
                                        setShowPreview(true);
                                    }}
                                    className="text-xs btn-secondary py-1.5 px-3 h-auto"
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
                                        className="text-xs px-2 py-1 rounded bg-[var(--danger)] text-white hover:bg-[var(--danger)]/80 disabled:opacity-50 min-w-[28px] flex items-center justify-center"
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
                                        className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:bg-white/5 flex items-center justify-center min-w-[28px]"
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
                                    className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--danger)] hover:text-[var(--danger)] transition-colors flex items-center justify-center min-w-[28px]"
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
