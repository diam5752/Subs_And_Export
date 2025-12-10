import { useEffect, useRef, useCallback } from 'react';
import { api, JobResponse } from '@/lib/api';

export interface JobPollingCallbacks {
    onProgress: (progress: number, message: string) => void;
    onComplete: (job: JobResponse) => void;
    onFailed: (errorMessage: string) => void;
    onError: (errorMessage: string) => void;
}

export interface UseJobPollingOptions {
    jobId: string | null;
    callbacks: JobPollingCallbacks;
    pollingInterval?: number;
    t: (key: string) => string;
}

export interface UseJobPollingResult {
    isPolling: boolean;
    stopPolling: () => void;
}

/**
 * Custom hook for polling job status.
 * Extracted from page.tsx to enable isolated testing.
 */
export function useJobPolling({
    jobId,
    callbacks,
    pollingInterval = 1000,
    t,
}: UseJobPollingOptions): UseJobPollingResult {
    const intervalRef = useRef<NodeJS.Timeout | null>(null);
    const isPollingRef = useRef(false);

    const stopPolling = useCallback(() => {
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }
        isPollingRef.current = false;
    }, []);

    useEffect(() => {
        if (!jobId) {
            stopPolling();
            return;
        }

        isPollingRef.current = true;

        const poll = async () => {
            try {
                const job = await api.getJobStatus(jobId);
                callbacks.onProgress(
                    job.progress,
                    job.message || (job.status === 'processing' ? t('statusProcessingEllipsis') : '')
                );

                if (job.status === 'completed') {
                    stopPolling();
                    callbacks.onComplete(job);
                } else if (job.status === 'failed') {
                    stopPolling();
                    callbacks.onFailed(job.message || t('statusFailedFallback'));
                }
            } catch {
                stopPolling();
                callbacks.onError(t('statusCheckFailed'));
            }
        };

        intervalRef.current = setInterval(poll, pollingInterval);

        return () => {
            stopPolling();
        };
    }, [jobId, callbacks, pollingInterval, t, stopPolling]);

    return {
        isPolling: isPollingRef.current,
        stopPolling,
    };
}
