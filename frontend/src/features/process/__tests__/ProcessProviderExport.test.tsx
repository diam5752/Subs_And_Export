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

function TranscriptPersistenceHarness() {
    const {
        cues,
        setCues,
        editingCueIndex,
        editingCueDraft,
        transcriptSaveError,
        beginEditingCue,
        handleUpdateDraft,
        saveEditingCue,
    } = useProcessContext();

    return (
        <div>
            <button
                type="button"
                onClick={() => setCues([{
                    start: 0,
                    end: 2,
                    text: 'ORIGINAL TEXT',
                    words: [
                        { start: 0, end: 1, text: 'ORIGINAL' },
                        { start: 1, end: 2, text: 'TEXT' },
                    ],
                }])}
            >
                seed-transcript
            </button>
            <button type="button" onClick={() => beginEditingCue(0)}>edit-first-cue</button>
            <input
                aria-label="transcript-draft"
                value={editingCueDraft}
                onChange={(event) => handleUpdateDraft(event.target.value)}
            />
            <button type="button" onClick={() => void saveEditingCue()}>save-transcript</button>
            <div data-testid="persisted-cue-text">{cues[0]?.text ?? ''}</div>
            <div data-testid="editing-cue-index">{editingCueIndex ?? 'none'}</div>
            <div data-testid="transcript-save-error">{transcriptSaveError ?? ''}</div>
        </div>
    );
}

function TranscriptLoadHarness() {
    const { cues, transcriptLoadError } = useProcessContext();

    return (
        <div>
            <div data-testid="loaded-cue-text">{cues[0]?.text ?? ''}</div>
            <div data-testid="transcript-load-error">{transcriptLoadError ?? ''}</div>
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
            original_filename: 'E Isous.mp4',
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

function TranscriptTestBed() {
    return (
        <ProcessProvider {...baseProps}>
            <TranscriptPersistenceHarness />
        </ProcessProvider>
    );
}

const jobWithTranscript = {
    ...baseProps.selectedJob,
    result_data: {
        ...baseProps.selectedJob.result_data,
        transcription_url: '/static/artifacts/job-1/transcription.json',
    },
} as JobResponse;

function TranscriptLoadTestBed() {
    return (
        <ProcessProvider {...baseProps} selectedJob={jobWithTranscript}>
            <TranscriptLoadHarness />
        </ProcessProvider>
    );
}

describe('ProcessProvider export handling', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        localStorage.clear();
        (api.exportVideo as jest.Mock).mockRejectedValue(new Error('Export failed'));
        (api.updateJobTranscription as jest.Mock).mockResolvedValue({ status: 'ok' });
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
            expect(clickSpy).toHaveBeenCalled();
            const clickedLink = clickSpy.mock.instances.at(-1) as unknown as HTMLAnchorElement;
            expect(clickedLink.download).toBe('E Isous_subs.mp4');
            expect(clickedLink.href).toContain('download=true');
            expect(clickedLink.href).toContain('filename=E%20Isous_subs.mp4');
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

    it('persists an inline transcript correction before closing the shared editor', async () => {
        render(
            <I18nProvider initialLocale="en">
                <TranscriptTestBed />
            </I18nProvider>,
        );

        fireEvent.click(screen.getByRole('button', { name: 'seed-transcript' }));
        fireEvent.click(screen.getByRole('button', { name: 'edit-first-cue' }));
        fireEvent.change(screen.getByRole('textbox', { name: 'transcript-draft' }), {
            target: { value: 'Διορθωμένος υπότιτλος' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'save-transcript' }));

        await waitFor(() => {
            expect(api.updateJobTranscription).toHaveBeenCalledWith(
                'job-1',
                [expect.objectContaining({ text: 'Διορθωμένος υπότιτλος' })],
            );
            expect(screen.getByTestId('editing-cue-index')).toHaveTextContent('none');
        });
        expect(screen.getByTestId('persisted-cue-text')).toHaveTextContent('Διορθωμένος υπότιτλος');
        expect(screen.getByTestId('transcript-save-error')).toBeEmptyDOMElement();
    });

    it('rolls back the preview and keeps the editor open when persistence fails', async () => {
        (api.updateJobTranscription as jest.Mock).mockRejectedValueOnce(new Error('Save unavailable'));
        render(
            <I18nProvider initialLocale="en">
                <TranscriptTestBed />
            </I18nProvider>,
        );

        fireEvent.click(screen.getByRole('button', { name: 'seed-transcript' }));
        fireEvent.click(screen.getByRole('button', { name: 'edit-first-cue' }));
        fireEvent.change(screen.getByRole('textbox', { name: 'transcript-draft' }), {
            target: { value: 'unsaved subtitle' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'save-transcript' }));

        await waitFor(() => {
            expect(screen.getByTestId('transcript-save-error')).toHaveTextContent('Save unavailable');
        });
        expect(screen.getByTestId('persisted-cue-text')).toHaveTextContent('ORIGINAL TEXT');
        expect(screen.getByTestId('editing-cue-index')).toHaveTextContent('0');
        expect(screen.getByRole('textbox', { name: 'transcript-draft' })).toHaveValue('unsaved subtitle');
    });

    it('loads a valid server-backed transcript', async () => {
        const originalFetch = global.fetch;
        global.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: async () => [{ start: 0, end: 1, text: 'Loaded cue', words: [] }],
        } as Response) as jest.MockedFunction<typeof fetch>;

        try {
            render(
                <I18nProvider initialLocale="en">
                    <TranscriptLoadTestBed />
                </I18nProvider>,
            );

            await waitFor(() => {
                expect(screen.getByTestId('loaded-cue-text')).toHaveTextContent('Loaded cue');
            });
            expect(screen.getByTestId('transcript-load-error')).toBeEmptyDOMElement();
        } finally {
            global.fetch = originalFetch;
        }
    });

    it('surfaces an unavailable transcript without emitting a console error', async () => {
        const originalFetch = global.fetch;
        global.fetch = jest.fn().mockResolvedValue({
            ok: false,
            status: 404,
            json: async () => ({}),
        } as Response) as jest.MockedFunction<typeof fetch>;
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => { });

        try {
            render(
                <I18nProvider initialLocale="en">
                    <TranscriptLoadTestBed />
                </I18nProvider>,
            );

            await waitFor(() => {
                expect(screen.getByTestId('transcript-load-error')).toHaveTextContent(
                    'The transcript is no longer available',
                );
            });
            expect(screen.getByTestId('loaded-cue-text')).toBeEmptyDOMElement();
            expect(consoleErrorSpy).not.toHaveBeenCalled();
        } finally {
            global.fetch = originalFetch;
            consoleErrorSpy.mockRestore();
        }
    });
});
