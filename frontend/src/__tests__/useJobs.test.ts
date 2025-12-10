
import { renderHook, act, waitFor } from '@testing-library/react';
import { useJobs } from '@/hooks/useJobs';
import { api } from '@/lib/api';

// Mock dependencies
jest.mock('@/lib/api', () => ({
    api: {
        getJobs: jest.fn(),
    },
}));

const mockUseAuth = jest.fn();
jest.mock('@/context/AuthContext', () => ({
    useAuth: () => mockUseAuth(),
}));

const mockUseI18n = jest.fn();
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => mockUseI18n(),
}));

describe('useJobs Hook', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockUseAuth.mockReturnValue({ user: { id: '123' } });
        mockUseI18n.mockReturnValue({ t: (key: string) => key });
    });

    it('should load jobs and sort them correctly', async () => {
        const jobs = [
            { id: '1', created_at: 100, updated_at: 100, status: 'pending' },
            { id: '2', created_at: 200, updated_at: 200, status: 'completed' },
        ];
        (api.getJobs as jest.Mock).mockResolvedValue(jobs);

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            await result.current.loadJobs();
        });

        expect(result.current.recentJobs).toHaveLength(2);
        expect(result.current.recentJobs[0].id).toBe('2'); // Newer one first
        expect(result.current.recentJobs[1].id).toBe('1');
        expect(result.current.jobsError).toBe('');
    });

    it('should not load jobs if user is not authenticated', async () => {
        mockUseAuth.mockReturnValue({ user: null });

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            await result.current.loadJobs();
        });

        expect(api.getJobs).not.toHaveBeenCalled();
    });

    it('should handle errors when loading jobs', async () => {
        (api.getJobs as jest.Mock).mockRejectedValue(new Error('Network error'));

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            await result.current.loadJobs();
        });

        expect(result.current.jobsError).toBe('Network error');
        expect(result.current.jobsLoading).toBe(false);
    });

    it('should fallback to default error message if error is not an Error object', async () => {
        (api.getJobs as jest.Mock).mockRejectedValue('String error');
        mockUseI18n.mockReturnValue({ t: (key: string) => key === 'jobsErrorFallback' ? 'Fallback Error' : key });

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            await result.current.loadJobs();
        });

        expect(result.current.jobsError).toBe('Fallback Error');
    });

    it('should auto-select the latest completed job if requested', async () => {
        const jobs = [
            { id: '1', created_at: 100, status: 'pending' },
            { id: '2', created_at: 200, status: 'completed', result_data: { video_path: 'foo' } },
            { id: '3', created_at: 150, status: 'failed' }
        ];
        (api.getJobs as jest.Mock).mockResolvedValue(jobs);

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            // Pass true for autoSelectLatest
            await result.current.loadJobs(true);
        });

        expect(result.current.selectedJob?.id).toBe('2');
    });
});
