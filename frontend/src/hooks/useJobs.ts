import { useState, useCallback, useEffect } from 'react';
import { api, JobResponse } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';

const DEFAULT_PAGE_SIZE = 5;

export function useJobs() {
    const { user } = useAuth();
    const { t } = useI18n();

    const [selectedJob, setSelectedJob] = useState<JobResponse | null>(null);
    const [recentJobs, setRecentJobs] = useState<JobResponse[]>([]);
    const [jobsLoading, setJobsLoading] = useState(false);
    const [jobsError, setJobsError] = useState('');

    // Pagination state
    const [currentPage, setCurrentPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [totalJobs, setTotalJobs] = useState(0);
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

    const fetchJobsPage = useCallback(async (autoSelectLatest: boolean, page: number) => {
        if (!user) return;
        setJobsLoading(true);
        setJobsError('');

        try {
            const response = await api.getJobsPaginated(page, pageSize);
            setRecentJobs(response.items);
            setCurrentPage(response.page);
            setTotalPages(response.total_pages);
            setTotalJobs(response.total);

            if (autoSelectLatest) {
                const latest = response.items.find(
                    (job) => job.status === 'completed'
                        && job.result_data
                        && !job.result_data.files_missing,
                );
                if (latest) {
                    setSelectedJob(prev => prev || latest);
                }
            }
        } catch (err) {
            setJobsError(err instanceof Error ? err.message : t('jobsErrorFallback'));
        } finally {
            setJobsLoading(false);
        }
    }, [pageSize, t, user]);

    const loadJobs = useCallback(async (autoSelectLatest = false, page?: number) => {
        await fetchJobsPage(autoSelectLatest, page ?? currentPage);
    }, [currentPage, fetchJobsPage]);

    const nextPage = useCallback(() => {
        if (currentPage < totalPages) {
            const newPage = currentPage + 1;
            setCurrentPage(newPage);
            loadJobs(false, newPage);
        }
    }, [currentPage, totalPages, loadJobs]);

    const prevPage = useCallback(() => {
        if (currentPage > 1) {
            const newPage = currentPage - 1;
            setCurrentPage(newPage);
            loadJobs(false, newPage);
        }
    }, [currentPage, loadJobs]);

    const goToPage = useCallback((page: number) => {
        if (page >= 1 && page <= totalPages) {
            setCurrentPage(page);
            loadJobs(false, page);
        }
    }, [totalPages, loadJobs]);

    const changePageSize = useCallback((newSize: number) => {
        setPageSize(newSize);
        setCurrentPage(1);
        // Will reload on next effect cycle
    }, []);

    // Initial load
    useEffect(() => {
        if (user) {
            void fetchJobsPage(false, 1);
        }
    }, [fetchJobsPage, user]);

    return {
        selectedJob,
        setSelectedJob,
        recentJobs,
        jobsLoading,
        jobsError,
        loadJobs,
        // Pagination
        currentPage,
        totalPages,
        totalJobs,
        pageSize,
        nextPage,
        prevPage,
        goToPage,
        changePageSize,
    };
}
