import { useEffect, useRef, useCallback, useState } from 'react';
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
    const [isPolling, setIsPolling] = useState(false);
    const isPollingRef = useRef(false);
    const inFlightRef = useRef(false);

    const stopPolling = useCallback(() => {
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }
        isPollingRef.current = false;
        setIsPolling(false);
    }, []);

    useEffect(() => {
        if (!jobId) {
            // Avoid setting state synchronously
            if (isPollingRef.current) {
                setTimeout(() => stopPolling(), 0);
            }
            return;
        }

        isPollingRef.current = true;
        setTimeout(() => setIsPolling(true), 0);

        const poll = async () => {
            if (!isPollingRef.current || inFlightRef.current) return;
            inFlightRef.current = true;
            try {
                const job = await api.getJobStatus(jobId);
                if (!isPollingRef.current) return;
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
                if (!isPollingRef.current) return;
                stopPolling();
                callbacks.onError(t('statusCheckFailed'));
            } finally {
                inFlightRef.current = false;
            }
        };

        intervalRef.current = setInterval(() => {
            void poll();
        }, pollingInterval);
        void poll();

        return () => {
            stopPolling();
        };
    }, [jobId, callbacks, pollingInterval, t, stopPolling]);

    return {
        isPolling,
        stopPolling,
    };
}
