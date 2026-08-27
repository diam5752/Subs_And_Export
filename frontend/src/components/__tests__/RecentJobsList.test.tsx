import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { RecentJobsList } from '../RecentJobsList';
import { api } from '@/lib/api';
import type { JobResponse } from '@/lib/api';

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({
        t: (key: string) => {
            if (key === 'paginationShowing') {
                return 'Showing {start}-{end} of {total}';
            }
            return key;
        },
    }),
}));

jest.mock('@/lib/api', () => ({
    api: {
        deleteJob: jest.fn(),
        deleteJobs: jest.fn(),
        createArtifactDownloadGrant: jest.fn(),
    },
}));

jest.mock('../JobListItem', () => ({
    JobListItem: ({
        job,
        isSelected,
        isConfirmingDelete,
        onToggleSelection,
        setConfirmDeleteId,
        onDeleteConfirmed,
        onDownload,
        isDownloading,
    }: {
        job: JobResponse;
        isSelected: boolean;
        isConfirmingDelete: boolean;
        onToggleSelection: (id: string, isSelected: boolean) => void;
        setConfirmDeleteId: (id: string | null) => void;
        onDeleteConfirmed: (id: string) => void;
        onDownload: (job: JobResponse) => void;
        isDownloading: boolean;
    }) => (
        <div data-testid={`job-${job.id}`}>
            <span>{job.result_data?.original_filename}</span>
            <span>{isSelected ? 'selected' : 'not-selected'}</span>
            <button type="button" onClick={() => onToggleSelection(job.id, isSelected)}>
                toggle-{job.id}
            </button>
            <button type="button" onClick={() => setConfirmDeleteId(job.id)}>
                ask-delete-{job.id}
            </button>
            <button type="button" onClick={() => onDownload(job)}>
                download-{job.id}
            </button>
            <span>{isDownloading ? `downloading-${job.id}` : `idle-${job.id}`}</span>
            {isConfirmingDelete ? (
                <button type="button" onClick={() => onDeleteConfirmed(job.id)}>
                    delete-{job.id}
                </button>
            ) : null}
        </div>
    ),
}));

const jobs: JobResponse[] = [
    {
        id: 'job-1',
        status: 'completed',
        progress: 100,
        message: null,
        created_at: 100,
        updated_at: 100,
        result_data: {
            original_filename: 'first.mp4',
            video_path: '/static/artifacts/job-1/processed.mp4',
            public_url: '/static/artifacts/job-1/processed.mp4',
            artifacts_dir: '/artifacts/job-1',
        },
    },
    {
        id: 'job-2',
        status: 'completed',
        progress: 100,
        message: null,
        created_at: 200,
        updated_at: 200,
        result_data: {
            original_filename: 'second.mp4',
            video_path: '/static/artifacts/job-2/processed.mp4',
            public_url: '/static/artifacts/job-2/processed.mp4',
            artifacts_dir: '/artifacts/job-2',
        },
    },
];

function renderList(overrides: Partial<React.ComponentProps<typeof RecentJobsList>> = {}) {
    return render(
        <RecentJobsList
            jobs={jobs}
            isLoading={false}
            onJobSelect={jest.fn()}
            selectedJobId={undefined}
            onRefreshJobs={jest.fn(async () => { })}
            formatDate={() => '2026-04-19'}
            buildStaticUrl={(path) => path ?? null}
            setShowPreview={jest.fn()}
            currentPage={1}
            totalPages={2}
            onNextPage={jest.fn()}
            onPrevPage={jest.fn()}
            totalJobs={4}
            pageSize={2}
            {...overrides}
        />,
    );
}

describe('RecentJobsList', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        Object.defineProperty(window, 'requestAnimationFrame', {
            writable: true,
            value: (callback: FrameRequestCallback) => {
                callback(0);
                return 1;
            },
        });
    });

    it('renders the empty state when there are no jobs', () => {
        renderList({ jobs: [], totalPages: 1, totalJobs: 0 });

        expect(screen.getByText('noHistory')).toBeInTheDocument();
        expect(screen.getByText('noRunsYet')).toBeInTheDocument();
    });

    it('supports batch selection and batch deletion', async () => {
        const onJobSelect = jest.fn();
        const onRefreshJobs = jest.fn(async () => { });
        const setShowPreview = jest.fn();
        (api.deleteJobs as jest.Mock).mockResolvedValue({});

        renderList({
            onJobSelect,
            onRefreshJobs,
            setShowPreview,
            selectedJobId: 'job-1',
        });

        fireEvent.click(screen.getByRole('button', { name: 'selectMode' }));
        fireEvent.click(screen.getByRole('button', { name: 'toggle-job-1' }));
        fireEvent.click(screen.getByRole('button', { name: 'toggle-job-2' }));

        expect(screen.getByText('2 selected')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /deleteSelected/i }));
        expect(screen.getByText('deleteSelectedConfirm')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'confirmDelete' }));

        await waitFor(() => {
            expect(api.deleteJobs).toHaveBeenCalledWith(['job-1', 'job-2']);
            expect(onRefreshJobs).toHaveBeenCalled();
            expect(onJobSelect).toHaveBeenCalledWith(null);
            expect(setShowPreview).toHaveBeenCalledWith(false);
        });
    });

    it('cancels selection mode and clears batch state', () => {
        renderList();

        fireEvent.click(screen.getByRole('button', { name: 'selectMode' }));
        fireEvent.click(screen.getByRole('button', { name: 'toggle-job-1' }));
        fireEvent.click(screen.getByRole('button', { name: /deleteSelected/i }));

        fireEvent.click(screen.getByRole('button', { name: 'cancelSelect' }));

        expect(screen.queryByText('1 selected')).not.toBeInTheDocument();
        expect(screen.queryByText('deleteSelectedConfirm')).not.toBeInTheDocument();
    });

    it('deletes a single job and clears the preview when deleting the selected one', async () => {
        const onJobSelect = jest.fn();
        const onRefreshJobs = jest.fn(async () => { });
        const setShowPreview = jest.fn();
        (api.deleteJob as jest.Mock).mockResolvedValue({});

        renderList({
            selectedJobId: 'job-1',
            onJobSelect,
            onRefreshJobs,
            setShowPreview,
        });

        fireEvent.click(screen.getByRole('button', { name: 'ask-delete-job-1' }));
        fireEvent.click(screen.getByRole('button', { name: 'delete-job-1' }));

        await waitFor(() => {
            expect(api.deleteJob).toHaveBeenCalledWith('job-1');
            expect(onJobSelect).toHaveBeenCalledWith(null);
            expect(setShowPreview).toHaveBeenCalledWith(false);
            expect(onRefreshJobs).toHaveBeenCalled();
        });
    });

    it('downloads history artifacts through a short-lived cross-browser grant', async () => {
        const anchorClick = jest
            .spyOn(HTMLAnchorElement.prototype, 'click')
            .mockImplementation(() => { });
        (api.createArtifactDownloadGrant as jest.Mock).mockResolvedValue({
            download_url: '/static/artifacts/job-1/processed.mp4?grant=history-grant',
            expires_in: 300,
        });

        renderList();
        fireEvent.click(screen.getByRole('button', { name: 'download-job-1' }));

        expect(screen.getByText('downloading-job-1')).toBeInTheDocument();
        await waitFor(() => {
            expect(api.createArtifactDownloadGrant).toHaveBeenCalledWith(
                'job-1',
                '/static/artifacts/job-1/processed.mp4',
                'first_subs.mp4',
            );
            expect(anchorClick).toHaveBeenCalledTimes(1);
        });
        await waitFor(() => {
            expect(screen.getByText('idle-job-1')).toBeInTheDocument();
        });

        const anchor = anchorClick.mock.contexts[0] as HTMLAnchorElement;
        expect(anchor.href).toContain(
            '/static/artifacts/job-1/processed.mp4?grant=history-grant',
        );
        expect(anchor.download).toBe('first_subs.mp4');
        anchorClick.mockRestore();
    });

    it('shows a retryable error when the history grant cannot be created', async () => {
        const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => { });
        (api.createArtifactDownloadGrant as jest.Mock).mockRejectedValue(
            new Error('grant failed'),
        );

        renderList();
        fireEvent.click(screen.getByRole('button', { name: 'download-job-1' }));

        expect(await screen.findByRole('alert')).toHaveTextContent('downloadError');
        expect(errorSpy).toHaveBeenCalledWith(
            'History download failed:',
            expect.any(Error),
        );
        errorSpy.mockRestore();
    });

    it('rejects a grant response that cannot be mapped to a download URL', async () => {
        const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => { });
        (api.createArtifactDownloadGrant as jest.Mock).mockResolvedValue({
            download_url: '/static/artifacts/job-1/processed.mp4?grant=invalid-url',
            expires_in: 300,
        });

        renderList({ buildStaticUrl: () => null });
        fireEvent.click(screen.getByRole('button', { name: 'download-job-1' }));

        expect(await screen.findByRole('alert')).toHaveTextContent('downloadError');
        expect(errorSpy).toHaveBeenCalledWith(
            'History download failed:',
            expect.objectContaining({
                message: 'Download grant did not include a usable URL',
            }),
        );
        errorSpy.mockRestore();
    });

    it('logs single-delete failures without crashing', async () => {
        const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => { });
        (api.deleteJob as jest.Mock).mockRejectedValue(new Error('delete failed'));

        renderList();

        fireEvent.click(screen.getByRole('button', { name: 'ask-delete-job-1' }));
        fireEvent.click(screen.getByRole('button', { name: 'delete-job-1' }));

        await waitFor(() => {
            expect(errorSpy).toHaveBeenCalledWith('Delete failed:', expect.any(Error));
        });
    });

    it('renders pagination controls and forwards page navigation callbacks', () => {
        const onPrevPage = jest.fn();
        const onNextPage = jest.fn();

        renderList({
            currentPage: 2,
            totalPages: 3,
            totalJobs: 5,
            pageSize: 2,
            onPrevPage,
            onNextPage,
        });

        expect(screen.getByText('Showing 3-4 of 5')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /previousPage/i }));
        fireEvent.click(screen.getByRole('button', { name: /nextPage/i }));

        expect(onPrevPage).toHaveBeenCalled();
        expect(onNextPage).toHaveBeenCalled();
    });
});
