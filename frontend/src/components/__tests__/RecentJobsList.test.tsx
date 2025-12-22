import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import { RecentJobsList } from '../RecentJobsList';
import { JobResponse, api } from '@/lib/api';

// Mock I18nContext
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

// Mock API
jest.mock('@/lib/api', () => ({
    api: {
        deleteJobs: jest.fn(),
        deleteJob: jest.fn(),
    },
}));

// Mock JobListItem to simplify testing
jest.mock('../JobListItem', () => ({
    JobListItem: () => <div data-testid="job-item">Job Item</div>
}));

describe('RecentJobsList', () => {
    const mockJobs: JobResponse[] = [{
        id: 'job-1',
        status: 'completed',
        progress: 100,
        message: null,
        created_at: 1625000000,
        updated_at: 1625000000,
        result_data: {
            video_path: '/path/to/video.mp4',
            artifacts_dir: '/artifacts',
            original_filename: 'test-video.mp4',
            public_url: 'http://example.com/video.mp4'
        }
    }];

    const defaultProps = {
        jobs: mockJobs,
        isLoading: false,
        onJobSelect: jest.fn(),
        selectedJobId: undefined,
        onRefreshJobs: jest.fn(),
        formatDate: () => '2021-06-29',
        buildStaticUrl: (path: string) => path,
        setShowPreview: jest.fn(),
        currentPage: 1,
        totalPages: 1,
        onNextPage: jest.fn(),
        onPrevPage: jest.fn(),
        totalJobs: 1,
        pageSize: 10,
    };

    it('shows spinner and accessible busy state during batch delete', async () => {
        // Mock slow delete
        let resolveDelete: (value: unknown) => void;
        const deletePromise = new Promise(resolve => {
            resolveDelete = resolve;
        });
        (api.deleteJobs as jest.Mock).mockReturnValue(deletePromise);

        render(<RecentJobsList {...defaultProps} />);

        // Enter selection mode
        fireEvent.click(screen.getByText('selectMode'));

        // Select all
        fireEvent.click(screen.getByText('selectAll'));

        // Click Delete Selected
        // The button text includes count: "deleteSelected (1)"
        // We use regex or partial match
        fireEvent.click(screen.getByText(/deleteSelected/));

        // Now confirm delete button is visible
        const confirmBtn = screen.getByText('confirmDelete');
        expect(confirmBtn).toBeInTheDocument();

        // Click confirm
        fireEvent.click(confirmBtn);

        // Expect spinner and busy state
        // The button text changes from 'confirmDelete' to spinner
        // We look for aria-busy="true"
        const busyBtn = document.querySelector('button[aria-busy="true"]');
        expect(busyBtn).toBeInTheDocument();

        // Check if spinner is inside (svg with animate-spin)
        const spinner = busyBtn?.querySelector('svg.animate-spin');
        expect(spinner).toBeInTheDocument();

        // Resolve the promise to clean up
        await act(async () => {
            resolveDelete(null);
        });
    });
});
