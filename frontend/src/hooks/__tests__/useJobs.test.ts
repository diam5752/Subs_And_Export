
import { renderHook, act, waitFor } from '@testing-library/react';
import { useJobs } from '../useJobs';
import { api } from '@/lib/api';

// Mock api
jest.mock('@/lib/api', () => ({
    api: {
        getJobsPaginated: jest.fn()
    }
}));

// Mock contexts
const mockUser = { id: 'user1' };
const mockUseAuth = jest.fn(() => ({ user: mockUser }));
jest.mock('@/context/AuthContext', () => ({
    useAuth: () => mockUseAuth()
}));

const mockT = jest.fn((key) => key);
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: mockT })
}));

describe('useJobs Hook', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockUseAuth.mockReturnValue({ user: mockUser });
    });

    it('loads jobs on mount if user exists', async () => {
        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [{ id: '1', status: 'completed' }],
            total: 10,
            page: 1,
            size: 5,
            total_pages: 2
        });

        const { result } = renderHook(() => useJobs());

        // Initially loading (maybe not immediately true due to async nature, but we check final state)
        // Actually, initial loading state might be false until effect runs

        await waitFor(() => {
            expect(result.current.recentJobs).toHaveLength(1);
        });

        expect(result.current.jobsLoading).toBe(false);
        expect(result.current.totalJobs).toBe(10);
        expect(result.current.totalPages).toBe(2);
    });

    it('does not load jobs if user is null', async () => {
        mockUseAuth.mockReturnValue({ user: null });
        (api.getJobsPaginated as jest.Mock).mockResolvedValue({});

        const { result } = renderHook(() => useJobs());

        // Should not call api
        // Wait a bit to be sure
        await new Promise(r => setTimeout(r, 100));

        expect(api.getJobsPaginated).not.toHaveBeenCalled();
        expect(result.current.recentJobs).toHaveLength(0);
    });

    it('auto-selects latest completed job on initial load', async () => {
        const job1 = { id: '1', status: 'completed', result_data: { video_path: 'v1' } };
        const job2 = { id: '2', status: 'pending' };

        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [job1, job2],
            total: 2,
            page: 1,
            size: 5,
            total_pages: 1
        });

        const { result } = renderHook(() => useJobs());

        await waitFor(() => {
            expect(result.current.selectedJob).toEqual(job1);
        });
    });

    it('handles pagination: nextPage', async () => {
        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [],
            total: 20,
            page: 1,
            size: 5,
            total_pages: 4
        });

        const { result } = renderHook(() => useJobs());

        await waitFor(() => expect(result.current.totalPages).toBe(4));

        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [{ id: 'p2' }],
            total: 20,
            page: 2,
            size: 5,
            total_pages: 4
        });

        await act(async () => {
            result.current.nextPage();
        });

        expect(result.current.currentPage).toBe(2);
        expect(api.getJobsPaginated).toHaveBeenCalledWith(2, 5);
    });

    it('handles pagination: prevPage', async () => {
        // Setup initial state as page 2
        // We can simulate this by initializing differently or walking there.
        // Or just manually calling loadJobs or goToPage if we could.
        // Actually, we can just start at page 1, set total pages, then goToPage 2, then prevPage.

        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [],
            total: 20,
            page: 1,
            size: 5,
            total_pages: 4
        });

        const { result } = renderHook(() => useJobs());
        await waitFor(() => expect(result.current.totalPages).toBe(4));

        // Go to page 2 first
        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [],
            total: 20,
            page: 2,
            size: 5,
            total_pages: 4
        });
        await act(async () => {
            result.current.goToPage(2);
        });
        expect(result.current.currentPage).toBe(2);

        // Now prev page
        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [],
            total: 20,
            page: 1,
            size: 5,
            total_pages: 4
        });
        await act(async () => {
            result.current.prevPage();
        });
        expect(result.current.currentPage).toBe(1);
    });

    it('handles pagination blocking (at boundaries)', async () => {
        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [],
            total: 5,
            page: 1,
            size: 5,
            total_pages: 1
        });

        const { result } = renderHook(() => useJobs());
        await waitFor(() => expect(result.current.totalPages).toBe(1));

        // Try next page (should fail)
        await act(async () => {
            result.current.nextPage();
        });
        expect(result.current.currentPage).toBe(1);

        // Try prev page (should fail)
        await act(async () => {
            result.current.prevPage();
        });
        expect(result.current.currentPage).toBe(1);
    });

    it('handles API errors', async () => {
        (api.getJobsPaginated as jest.Mock).mockRejectedValue(new Error('Fetch failed'));

        const { result } = renderHook(() => useJobs());

        await waitFor(() => {
            expect(result.current.jobsError).toBe('Fetch failed');
        });
        expect(result.current.jobsLoading).toBe(false);
    });

    it('updates page size', async () => {
        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [],
            total: 20,
            page: 1,
            size: 5,
            total_pages: 4
        });

        const { result } = renderHook(() => useJobs());
        await waitFor(() => expect(result.current.pageSize).toBe(5));

        // Change size
        await act(async () => {
            result.current.changePageSize(10);
        });

        expect(result.current.pageSize).toBe(10);
        expect(result.current.currentPage).toBe(1); // Resets to 1

        // Effect should trigger reload with new size
        await waitFor(() => {
            expect(api.getJobsPaginated).toHaveBeenCalledWith(1, 10);
        });
    });

    it('allows manual reload', async () => {
        (api.getJobsPaginated as jest.Mock).mockResolvedValue({
            items: [],
            total: 10,
            page: 1,
            size: 5,
            total_pages: 2
        });

        const { result } = renderHook(() => useJobs());
        await waitFor(() => expect(result.current.jobsLoading).toBe(false));

        // Reload
        await act(async () => {
            await result.current.loadJobs(false);
        });

        expect(api.getJobsPaginated).toHaveBeenCalledTimes(2); // Initial + Manual
    });
});
