import { useState, useCallback, useEffect } from 'react';
import { api, JobResponse } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { useI18n } from '@/context/I18nContext';

export function useJobs() {
    const { user } = useAuth();
    const { t } = useI18n();

    const [selectedJob, setSelectedJob] = useState<JobResponse | null>(null);
    const [recentJobs, setRecentJobs] = useState<JobResponse[]>([]);
    const [jobsLoading, setJobsLoading] = useState(false);
    const [jobsError, setJobsError] = useState('');

    const loadJobs = useCallback(async (autoSelectLatest = false) => {
        if (!user) return;
        setJobsLoading(true);
        setJobsError('');
        try {
            const jobs = await api.getJobs();
            const sorted = [...jobs].sort(
                (a, b) => (b.updated_at || b.created_at) - (a.updated_at || a.created_at)
            );
            setRecentJobs(sorted);

            if (autoSelectLatest && !selectedJob) {
                const latest = sorted.find((job) => job.status === 'completed' && job.result_data);
                if (latest) {
                    setSelectedJob(latest);
                }
            }
        } catch (err) {
            setJobsError(err instanceof Error ? err.message : t('jobsErrorFallback'));
        } finally {
            setJobsLoading(false);
        }
    }, [user, selectedJob, t]);

    // Initial load
    useEffect(() => {
        if (user) {
            loadJobs(true);
        }
    }, [user, loadJobs]);

    return {
        selectedJob,
        setSelectedJob,
        recentJobs,
        jobsLoading,
        jobsError,
        loadJobs,
    };
}
