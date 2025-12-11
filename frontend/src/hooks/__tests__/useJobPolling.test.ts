import { renderHook, act } from '@testing-library/react';
import { useJobPolling, JobPollingCallbacks } from '../useJobPolling';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
    api: {
        getJobStatus: jest.fn(),
    },
}));

describe('useJobPolling', () => {
    const mockT = (key: string) => key;
    const createMockCallbacks = (): JobPollingCallbacks => ({
        onProgress: jest.fn(),
        onComplete: jest.fn(),
        onFailed: jest.fn(),
        onError: jest.fn(),
    });

    beforeEach(() => {
        jest.clearAllMocks();
        jest.useFakeTimers();
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    it('should not poll when jobId is null', () => {
        const callbacks = createMockCallbacks();
        renderHook(() => useJobPolling({
            jobId: null,
            callbacks,
            t: mockT,
        }));

        act(() => {
            jest.advanceTimersByTime(2000);
        });

        expect(api.getJobStatus).not.toHaveBeenCalled();
    });

    it('should poll for job status when jobId is provided', async () => {
        const callbacks = createMockCallbacks();
        (api.getJobStatus as jest.Mock).mockResolvedValue({
            id: 'job-1',
            status: 'processing',
            progress: 50,
            message: 'Processing...',
        });

        renderHook(() => useJobPolling({
            jobId: 'job-1',
            callbacks,
            pollingInterval: 100,
            t: mockT,
        }));

        await act(async () => {
            jest.advanceTimersByTime(150);
            await Promise.resolve();
        });

        expect(api.getJobStatus).toHaveBeenCalledWith('job-1');
        expect(callbacks.onProgress).toHaveBeenCalledWith(50, 'Processing...');
    });

    it('should call onComplete when job status is completed', async () => {
        const callbacks = createMockCallbacks();
        const completedJob = {
            id: 'job-1',
            status: 'completed',
            progress: 100,
            message: 'Done',
            result_data: { public_url: 'url' },
        };
        (api.getJobStatus as jest.Mock).mockResolvedValue(completedJob);

        renderHook(() => useJobPolling({
            jobId: 'job-1',
            callbacks,
            pollingInterval: 100,
            t: mockT,
        }));

        await act(async () => {
            jest.advanceTimersByTime(150);
            await Promise.resolve();
        });

        expect(callbacks.onComplete).toHaveBeenCalledWith(completedJob);
    });

    it('should call onFailed when job status is failed', async () => {
        const callbacks = createMockCallbacks();
        (api.getJobStatus as jest.Mock).mockResolvedValue({
            id: 'job-1',
            status: 'failed',
            progress: 0,
            message: 'Job failed',
        });

        renderHook(() => useJobPolling({
            jobId: 'job-1',
            callbacks,
            pollingInterval: 100,
            t: mockT,
        }));

        await act(async () => {
            jest.advanceTimersByTime(150);
            await Promise.resolve();
        });

        expect(callbacks.onFailed).toHaveBeenCalledWith('Job failed');
    });

    it('should call onError when API throws', async () => {
        const callbacks = createMockCallbacks();
        (api.getJobStatus as jest.Mock).mockRejectedValue(new Error('Network error'));

        renderHook(() => useJobPolling({
            jobId: 'job-1',
            callbacks,
            pollingInterval: 100,
            t: mockT,
        }));

        await act(async () => {
            jest.advanceTimersByTime(150);
            await Promise.resolve();
        });

        expect(callbacks.onError).toHaveBeenCalledWith('statusCheckFailed');
    });

    it('should stop polling on unmount', async () => {
        const callbacks = createMockCallbacks();
        (api.getJobStatus as jest.Mock).mockResolvedValue({
            id: 'job-1',
            status: 'processing',
            progress: 50,
        });

        const { unmount } = renderHook(() => useJobPolling({
            jobId: 'job-1',
            callbacks,
            pollingInterval: 100,
            t: mockT,
        }));

        await act(async () => {
            jest.advanceTimersByTime(150);
            await Promise.resolve();
        });

        expect(api.getJobStatus).toHaveBeenCalledTimes(1);

        unmount();

        await act(async () => {
            jest.advanceTimersByTime(200);
            await Promise.resolve();
        });

        // Should not have been called again after unmount
        expect(api.getJobStatus).toHaveBeenCalledTimes(1);
    });

    it('should use default status message for processing status', async () => {
        const callbacks = createMockCallbacks();
        (api.getJobStatus as jest.Mock).mockResolvedValue({
            id: 'job-1',
            status: 'processing',
            progress: 25,
            message: null,
        });

        renderHook(() => useJobPolling({
            jobId: 'job-1',
            callbacks,
            pollingInterval: 100,
            t: mockT,
        }));

        await act(async () => {
            jest.advanceTimersByTime(150);
            await Promise.resolve();
        });

        expect(callbacks.onProgress).toHaveBeenCalledWith(25, 'statusProcessingEllipsis');
    });

    it('should use empty message for non-processing status', async () => {
        const callbacks = createMockCallbacks();
        (api.getJobStatus as jest.Mock).mockResolvedValue({
            id: 'job-1',
            status: 'pending',
            progress: 0,
            message: null,
        });

        renderHook(() => useJobPolling({
            jobId: 'job-1',
            callbacks,
            pollingInterval: 100,
            t: mockT,
        }));

        await act(async () => {
            jest.advanceTimersByTime(150);
            await Promise.resolve();
        });

        expect(callbacks.onProgress).toHaveBeenCalledWith(0, '');
    });

    it('should use default failed message when none provided', async () => {
        const callbacks = createMockCallbacks();
        (api.getJobStatus as jest.Mock).mockResolvedValue({
            id: 'job-1',
            status: 'failed',
            progress: 0,
            message: null,
        });

        renderHook(() => useJobPolling({
            jobId: 'job-1',
            callbacks,
            pollingInterval: 100,
            t: mockT,
        }));

        await act(async () => {
            jest.advanceTimersByTime(150);
            await Promise.resolve();
        });

        expect(callbacks.onFailed).toHaveBeenCalledWith('statusFailedFallback');
    });
});
