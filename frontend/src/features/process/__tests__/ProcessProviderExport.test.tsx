import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import { I18nProvider } from '@/context/I18nContext';
import { api } from '@/lib/api';
import type { JobResponse } from '@/lib/api';

import { ProcessProvider, useProcessContext } from '../ProcessContext';

jest.mock('@/lib/api', () => ({
    API_BASE: 'http://localhost:8080',
    api: {
        exportVideo: jest.fn(),
        getJobsPaginated: jest.fn(),
        updateJobTranscription: jest.fn(),
    },
}));

function ExportHarness() {
    const { handleExport, exportError, videoUrl } = useProcessContext();

    return (
        <div>
            <button type="button" onClick={() => void handleExport('srt')}>
                export-srt
            </button>
            <button type="button" onClick={() => void handleExport('vtt')}>
                export-vtt
            </button>
            <button type="button" onClick={() => void handleExport('1080x1920')}>
                export-1080
            </button>
            <div data-testid="video-url">{videoUrl ?? ''}</div>
            <div data-testid="export-error">{exportError ?? ''}</div>
        </div>
    );
}

const baseProps = {
    selectedFile: null,
    onFileSelect: jest.fn(),
    isProcessing: false,
    progress: 0,
    statusMessage: '',
    error: '',
    onStartProcessing: jest.fn(async () => { }),
    onReprocessJob: jest.fn(async () => { }),
    onReset: jest.fn(),
    onCancelProcessing: undefined,
    selectedJob: {
        id: 'job-1',
        status: 'completed',
        progress: 100,
        message: null,
        created_at: Date.now(),
        updated_at: Date.now(),
        result_data: {
            video_path: '/static/artifacts/job-1/processed.mp4',
            artifacts_dir: '/static/artifacts/job-1',
            public_url: '/static/artifacts/job-1/processed.mp4',
        },
    },
    onJobSelect: jest.fn(),
    statusStyles: {},
    buildStaticUrl: jest.fn(() => null),
    totalJobs: 1,
};

function ExportTestBed({ buildStaticUrl = baseProps.buildStaticUrl }: { buildStaticUrl?: (path?: string | null) => string | null }) {
    const [selectedJob, setSelectedJob] = React.useState<JobResponse | null>(baseProps.selectedJob);

    return (
        <ProcessProvider
            {...baseProps}
            selectedJob={selectedJob}
            onJobSelect={setSelectedJob}
            buildStaticUrl={buildStaticUrl}
        >
            <ExportHarness />
        </ProcessProvider>
    );
}

describe('ProcessProvider export handling', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        localStorage.clear();
        (api.exportVideo as jest.Mock).mockRejectedValue(new Error('Export failed'));
    });

    it('stores a visible export error when variant export fails', async () => {
        render(
            <I18nProvider initialLocale="en">
                <ExportTestBed />
            </I18nProvider>,
        );

        fireEvent.click(screen.getByRole('button', { name: 'export-srt' }));

        await waitFor(() => {
            expect(screen.getByTestId('export-error')).toHaveTextContent('Export failed');
        });
    });

    it('switches the preview to the freshly exported video variant', async () => {
        const updatedJob = {
            ...baseProps.selectedJob,
            result_data: {
                ...baseProps.selectedJob.result_data,
                variants: {
                    '1080x1920': '/static/artifacts/job-1/processed-1080.mp4',
                },
            },
        };
        const buildStaticUrl = jest.fn((path?: string | null) => path ? `https://static.local${path}` : null);
        const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { });
        (api.exportVideo as jest.Mock).mockResolvedValue(updatedJob);
        try {
            render(
                <I18nProvider initialLocale="en">
                    <ExportTestBed buildStaticUrl={buildStaticUrl} />
                </I18nProvider>,
            );

            fireEvent.click(screen.getByRole('button', { name: 'export-1080' }));

            await waitFor(() => {
                expect(screen.getByTestId('video-url')).toHaveTextContent('https://static.local/static/artifacts/job-1/processed-1080.mp4');
            });
            expect(api.exportVideo).toHaveBeenCalledWith('job-1', '1080x1920', expect.any(Object));
        } finally {
            clickSpy.mockRestore();
        }
    });

    it('downloads subtitle-file exports without switching the preview player variant', async () => {
        const updatedJob = {
            ...baseProps.selectedJob,
            result_data: {
                ...baseProps.selectedJob.result_data,
                variants: {
                    vtt: '/static/artifacts/job-1/processed.vtt',
                },
            },
        };
        const buildStaticUrl = jest.fn((path?: string | null) => path ? `https://static.local${path}` : null);
        const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { });
        (api.exportVideo as jest.Mock).mockResolvedValue(updatedJob);

        try {
            render(
                <I18nProvider initialLocale="en">
                    <ExportTestBed buildStaticUrl={buildStaticUrl} />
                </I18nProvider>,
            );

            expect(screen.getByTestId('video-url')).toHaveTextContent('https://static.local/static/artifacts/job-1/processed.mp4');

            fireEvent.click(screen.getByRole('button', { name: 'export-vtt' }));

            await waitFor(() => {
                expect(api.exportVideo).toHaveBeenCalledWith('job-1', 'vtt', expect.any(Object));
            });
            expect(screen.getByTestId('video-url')).toHaveTextContent('https://static.local/static/artifacts/job-1/processed.mp4');
        } finally {
            clickSpy.mockRestore();
        }
    });
});
