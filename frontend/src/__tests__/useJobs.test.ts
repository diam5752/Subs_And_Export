
import { renderHook, act, waitFor } from '@testing-library/react';
import { useJobs } from '@/hooks/useJobs';
import { api } from '@/lib/api';

// Mock dependencies
jest.mock('@/lib/api', () => ({
    api: {
        getJobsPaginated: jest.fn(),
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

    it('should load jobs from paginated API', async () => {
        const paginatedResponse = {
            items: [
                { id: '1', created_at: 100, updated_at: 100, status: 'pending' },
                { id: '2', created_at: 200, updated_at: 200, status: 'completed' },
            ],
            total: 2,
            page: 1,
            page_size: 5,
            total_pages: 1,
        };
        (api.getJobsPaginated as jest.Mock).mockResolvedValue(paginatedResponse);

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            await result.current.loadJobs();
        });

        expect(result.current.recentJobs).toHaveLength(2);
        expect(result.current.totalPages).toBe(1);
        expect(result.current.currentPage).toBe(1);
        expect(result.current.jobsError).toBe('');
    });

    it('should not load jobs if user is not authenticated', async () => {
        mockUseAuth.mockReturnValue({ user: null });

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            await result.current.loadJobs();
        });

        expect(api.getJobsPaginated).not.toHaveBeenCalled();
    });

    it('should handle errors when loading jobs', async () => {
        (api.getJobsPaginated as jest.Mock).mockRejectedValue(new Error('Network error'));

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            await result.current.loadJobs();
        });

        expect(result.current.jobsError).toBe('Network error');
        expect(result.current.jobsLoading).toBe(false);
    });

    it('should fallback to default error message if error is not an Error object', async () => {
        (api.getJobsPaginated as jest.Mock).mockRejectedValue('String error');
        mockUseI18n.mockReturnValue({ t: (key: string) => key === 'jobsErrorFallback' ? 'Fallback Error' : key });

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            await result.current.loadJobs();
        });

        expect(result.current.jobsError).toBe('Fallback Error');
    });

    it('should auto-select the latest completed job if requested', async () => {
        const paginatedResponse = {
            items: [
                { id: '1', created_at: 100, status: 'pending' },
                { id: '2', created_at: 200, status: 'completed', result_data: { video_path: 'foo' } },
                { id: '3', created_at: 150, status: 'failed' }
            ],
            total: 3,
            page: 1,
            page_size: 5,
            total_pages: 1,
        };
        (api.getJobsPaginated as jest.Mock).mockResolvedValue(paginatedResponse);

        const { result } = renderHook(() => useJobs());

        await act(async () => {
            // Pass true for autoSelectLatest
            await result.current.loadJobs(true);
        });

        expect(result.current.selectedJob?.id).toBe('2');
    });

    it('should navigate to next page', async () => {
        const page1Response = {
            items: [{ id: '1', created_at: 100, status: 'completed' }],
            total: 6,
            page: 1,
            page_size: 5,
            total_pages: 2,
        };
        const page2Response = {
            items: [{ id: '11', created_at: 200, status: 'completed' }],
            total: 6,
            page: 2,
            page_size: 5,
            total_pages: 2,
        };
        (api.getJobsPaginated as jest.Mock)
            .mockResolvedValueOnce(page1Response)
            .mockResolvedValueOnce(page2Response);

        const { result } = renderHook(() => useJobs());

        // Wait for initial load
        await waitFor(() => {
            expect(result.current.recentJobs).toHaveLength(1);
        });

        await act(async () => {
            result.current.nextPage();
        });

        await waitFor(() => {
            expect(result.current.currentPage).toBe(2);
        });
    });

    it('should navigate to previous page', async () => {
        const page2Response = {
            items: [{ id: '11', created_at: 200, status: 'completed' }],
            total: 6,
            page: 2,
            page_size: 5,
            total_pages: 2,
        };
        const page1Response = {
            items: [{ id: '1', created_at: 100, status: 'completed' }],
            total: 6,
            page: 1,
            page_size: 5,
            total_pages: 2,
        };
        (api.getJobsPaginated as jest.Mock)
            .mockResolvedValueOnce(page2Response)
            .mockResolvedValueOnce(page1Response);

        const { result } = renderHook(() => useJobs());

        // Wait for initial load (simulating page 2)
        await waitFor(() => {
            expect(result.current.recentJobs).toHaveLength(1);
        });

        // Manually set state before prevPage for this test
        await act(async () => {
            // First call sets page to 2
            result.current.prevPage();
        });

        // Since we're on page 1, prevPage shouldn't navigate further
        expect(result.current.currentPage).toBe(1);
    });
});

