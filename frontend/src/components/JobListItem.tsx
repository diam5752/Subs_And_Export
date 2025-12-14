import React, { memo } from 'react';
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
                    {job.result_data?.original_filename || job.id}
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
                                <a
                                    className="text-xs btn-primary py-1.5 px-3 h-auto"
                                    href={publicUrl}
                                    download={job.result_data?.original_filename || 'processed.mp4'}
                                    onClick={(e) => e.stopPropagation()}
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
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onDeleteConfirmed(job.id);
                                        }}
                                        disabled={isDeleting}
                                        className="text-xs px-2 py-1 rounded bg-[var(--danger)] text-white hover:bg-[var(--danger)]/80 disabled:opacity-50"
                                        aria-label={t('confirmDelete') || 'Confirm delete'}
                                    >
                                        {isDeleting ? '...' : '✓'}
                                    </button>
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            setConfirmDeleteId(null);
                                        }}
                                        className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:bg-white/5"
                                        aria-label={t('cancel') || 'Cancel'}
                                    >
                                        ✕
                                    </button>
                                </div>
                            ) : (
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setConfirmDeleteId(job.id);
                                    }}
                                    className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--danger)] hover:text-[var(--danger)] transition-colors"
                                    title={t('deleteJob')}
                                    aria-label={t('deleteJob') || 'Delete job'}
                                >
                                    🗑️
                                </button>
                            )
                        )}
                    </>
                )}
            </div>
        </div>
    );
});
