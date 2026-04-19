import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import { I18nProvider } from '@/context/I18nContext';
import { api } from '@/lib/api';

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
    const { handleExport, exportError } = useProcessContext();

    return (
        <div>
            <button type="button" onClick={() => void handleExport('srt')}>
                export-srt
            </button>
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

describe('ProcessProvider export handling', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        localStorage.clear();
        (api.exportVideo as jest.Mock).mockRejectedValue(new Error('Export failed'));
    });

    it('stores a visible export error when variant export fails', async () => {
        render(
            <I18nProvider initialLocale="en">
                <ProcessProvider {...baseProps}>
                    <ExportHarness />
                </ProcessProvider>
            </I18nProvider>,
        );

        fireEvent.click(screen.getByRole('button', { name: 'export-srt' }));

        await waitFor(() => {
            expect(screen.getByTestId('export-error')).toHaveTextContent('Export failed');
        });
    });
});
