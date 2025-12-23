import React, { memo, useState, useCallback, useRef, useEffect } from 'react';
import { api, JobResponse } from '@/lib/api';
import { useI18n } from '@/context/I18nContext';
import { JobListItem } from './JobListItem';

interface RecentJobsListProps {
    jobs: JobResponse[];
    isLoading: boolean;
    onJobSelect: (job: JobResponse | null) => void;
    selectedJobId: string | undefined;
    onRefreshJobs: () => Promise<void>;
    formatDate: (ts: number | string) => string;
    buildStaticUrl: (path?: string | null) => string | null;
    setShowPreview: (show: boolean) => void;
    // Pagination
    currentPage: number;
    totalPages: number;
    onNextPage: () => void;
    onPrevPage: () => void;
    totalJobs: number;
    pageSize: number;
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
    pageSize
}: RecentJobsListProps) {
    const { t } = useI18n();
    const [selectionMode, setSelectionMode] = useState(false);
    const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set());
    const [isBatchDeleting, setIsBatchDeleting] = useState(false);
    const [confirmBatchDelete, setConfirmBatchDelete] = useState(false);
    const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

    // Refs for focus management
    const batchDeleteBtnRef = useRef<HTMLButtonElement>(null);
    const confirmBatchBtnRef = useRef<HTMLButtonElement>(null);
    const prevBatchConfirmingRef = useRef(confirmBatchDelete);

    // Keep track of selectedJobId in a ref to avoid re-creating handleDeleteJob when it changes
    const selectedJobIdRef = useRef(selectedJobId);
    useEffect(() => {
        selectedJobIdRef.current = selectedJobId;
    }, [selectedJobId]);

    // Focus management for batch delete confirmation
    useEffect(() => {
        // Entering confirmation mode
        if (confirmBatchDelete && !prevBatchConfirmingRef.current) {
            requestAnimationFrame(() => {
                confirmBatchBtnRef.current?.focus();
            });
        }

        // Exiting confirmation mode (cancelling)
        if (!confirmBatchDelete && prevBatchConfirmingRef.current) {
            requestAnimationFrame(() => {
                batchDeleteBtnRef.current?.focus();
            });
        }

        prevBatchConfirmingRef.current = confirmBatchDelete;
    }, [confirmBatchDelete]);

    const handleDeleteJob = useCallback(async (jobId: string) => {
        setDeletingJobId(jobId);
        try {
            await api.deleteJob(jobId);
            if (selectedJobIdRef.current === jobId) {
                onJobSelect(null);
                setShowPreview(false);
            }
            setConfirmDeleteId(null);
            await onRefreshJobs();
        } catch (err) {
            console.error('Delete failed:', err);
        } finally {
            setDeletingJobId(null);
        }
    }, [onJobSelect, setShowPreview, onRefreshJobs]);

    const handleToggleSelection = useCallback((id: string, isSelected: boolean) => {
        setSelectedJobIds(prev => {
            const newSet = new Set(prev);
            if (isSelected) {
                newSet.delete(id);
            } else {
                newSet.add(id);
            }
            return newSet;
        });
    }, []);

    return (
        <div className="card mt-6 border-none bg-transparent shadow-none p-0">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <div>
                    <h3 className="text-lg font-semibold">{t('historyTitle') || 'History'}</h3>
                    <p className="text-xs text-[var(--muted)]">{t('historyExpiry') || 'Items expire in 24 hours'}</p>
                </div>
                <div className="flex items-center gap-2">
                    {isLoading && <span data-testid="jobs-loading" className="text-xs text-[var(--muted)]">{t('refreshingLabel')}</span>}
                    {jobs.length > 0 && (
                        <button
                            onClick={() => {
                                setSelectionMode(!selectionMode);
                                if (selectionMode) {
                                    setSelectedJobIds(new Set());
                                    setConfirmBatchDelete(false);
                                }
                            }}
                            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${selectionMode
                                ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                                : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                                }`}
                        >
                            {selectionMode ? (t('cancelSelect') || 'Cancel') : (t('selectMode') || 'Select')}
                        </button>
                    )}
                </div>
            </div>

            {/* Selection mode controls */}
            {selectionMode && jobs.length > 0 && (
                <div className="flex flex-wrap items-center gap-3 mb-3 p-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]">
                    <label className="flex items-center gap-2 cursor-pointer text-sm">
                        <input
                            type="checkbox"
                            checked={selectedJobIds.size === jobs.length && jobs.length > 0}
                            onChange={(e) => {
                                if (e.target.checked) {
                                    setSelectedJobIds(new Set(jobs.map(j => j.id)));
                                } else {
                                    setSelectedJobIds(new Set());
                                }
                            }}
                            className="w-4 h-4 rounded border-[var(--border)] accent-[var(--accent)]"
                        />
                        {selectedJobIds.size === jobs.length
                            ? (t('deselectAll') || 'Deselect All')
                            : (t('selectAll') || 'Select All')}
                    </label>
                    <span className="text-xs text-[var(--muted)]">
                        {selectedJobIds.size} {t('selected') || 'selected'}
                    </span>
                    <div className="flex-1" />
                    {confirmBatchDelete ? (
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-[var(--danger)]">
                                {t('deleteSelectedConfirm') || `Delete ${selectedJobIds.size} items?`}
                            </span>
                            <button
                                ref={confirmBatchBtnRef}
                                onClick={async () => {
                                    setIsBatchDeleting(true);
                                    try {
                                        await api.deleteJobs(Array.from(selectedJobIds));
                                        // If the currently selected job was deleted, clear selection
                                        if (selectedJobId && selectedJobIds.has(selectedJobId)) {
                                            onJobSelect(null);
                                            setShowPreview(false);
                                        }
                                        setSelectedJobIds(new Set());
                                        setConfirmBatchDelete(false);
                                        setSelectionMode(false);
                                        await onRefreshJobs();
                                    } catch (err) {
                                        console.error('Batch delete failed:', err);
                                    } finally {
                                        setIsBatchDeleting(false);
                                    }
                                }}
                                disabled={isBatchDeleting}
                                className="text-xs px-3 py-1.5 rounded bg-[var(--danger)] text-white hover:bg-[var(--danger)]/80 disabled:opacity-50 min-w-[60px]"
                            >
                                {isBatchDeleting ? '...' : (t('confirmDelete') || 'Confirm')}
                            </button>
                            <button
                                onClick={() => setConfirmBatchDelete(false)}
                                className="text-xs px-3 py-1.5 rounded border border-[var(--border)] hover:bg-white/5"
                            >
                                {t('cancel') || 'Cancel'}
                            </button>
                        </div>
                    ) : (
                        <button
                            ref={batchDeleteBtnRef}
                            onClick={() => setConfirmBatchDelete(true)}
                            disabled={selectedJobIds.size === 0}
                            className="text-xs px-3 py-1.5 rounded border border-[var(--danger)] text-[var(--danger)] hover:bg-[var(--danger)]/10 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            🗑️ {t('deleteSelected') || 'Delete Selected'} ({selectedJobIds.size})
                        </button>
                    )}
                </div>
            )}

            {jobs.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 px-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface-elevated)]/30 text-center animate-fade-in">
                    <div className="mb-3 p-3 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)] text-[var(--muted)] opacity-70">
                        <svg aria-hidden="true" className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <h4 className="text-sm font-semibold text-[var(--foreground)] mb-1">
                        {t('noHistory') || 'No history yet.'}
                    </h4>
                    <p className="text-xs text-[var(--muted)] max-w-[200px]">
                        {t('noRunsYet') || 'Your processed videos will appear here.'}
                    </p>
                </div>
            )}
            <div className="space-y-2">
                {jobs.map((job) => {
                    const publicUrl = buildStaticUrl(job.result_data?.public_url || job.result_data?.video_path);
                    const timestamp = (job.updated_at || job.created_at) * 1000;
                    const isExpired = (Date.now() - timestamp) > 24 * 60 * 60 * 1000;
                    const isSelected = selectedJobIds.has(job.id);

                    return (
                        <JobListItem
                            key={job.id}
                            job={job}
                            selectionMode={selectionMode}
                            isSelected={isSelected}
                            isExpired={isExpired}
                            publicUrl={publicUrl}
                            timestamp={timestamp}
                            formatDate={formatDate}
                            onToggleSelection={handleToggleSelection}
                            onJobSelect={onJobSelect}
                            setShowPreview={setShowPreview}
                            isConfirmingDelete={confirmDeleteId === job.id}
                            isDeleting={deletingJobId === job.id}
                            setConfirmDeleteId={setConfirmDeleteId}
                            onDeleteConfirmed={handleDeleteJob}
                            t={t as (key: string) => string}
                        />
                    );
                })}
            </div>

            {/* Pagination Controls */}
            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-4 mt-4 pt-4 border-t border-[var(--border)]">
                    <button
                        onClick={onPrevPage}
                        disabled={currentPage <= 1}
                        className="text-sm px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                        ← {t('previousPage') || 'Previous'}
                    </button>
                    <span className="text-sm text-[var(--muted)]">
                        {(() => {
                            const start = (currentPage - 1) * pageSize + 1;
                            const end = Math.min(currentPage * pageSize, totalJobs);
                            return t('paginationShowing')
                                ? t('paginationShowing').replace('{start}', String(start)).replace('{end}', String(end)).replace('{total}', String(totalJobs))
                                : `Showing ${start}-${end} of ${totalJobs}`;
                        })()}
                    </span>
                    <button
                        onClick={onNextPage}
                        disabled={currentPage >= totalPages}
                        className="text-sm px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                        {t('nextPage') || 'Next'} →
                    </button>
                </div>
            )}
        </div>
    );
});
