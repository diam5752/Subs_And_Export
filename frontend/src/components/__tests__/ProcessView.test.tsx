/**
 * Coverage for ProcessView interactions: thumbnail generation and preview cleanup.
 */
import React, { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { I18nProvider } from '@/context/I18nContext';
import { ProcessView } from '../ProcessView';
import type { JobResponse } from '@/lib/api';

jest.mock('@/lib/api', () => {
    const actual = jest.requireActual('@/lib/api');
    const deleteJob = jest.fn();
    return {
        ...actual,
        api: {
            ...actual.api,
            deleteJob,
        },
        __deleteJobMock: deleteJob,
    };
});

const { __deleteJobMock } = jest.requireMock('@/lib/api');
const deleteJobMock = __deleteJobMock as jest.Mock;

const statusStyles = {
    completed: 'completed',
    processing: 'processing',
    pending: 'pending',
    failed: 'failed',
};

const formatDate = (ts: string | number) => new Date(ts).toISOString();
const buildStaticUrl = (path?: string | null) => (path ? path : null);

type WrapperProps = Partial<React.ComponentProps<typeof ProcessView>>;

function ProcessViewWrapper(props: WrapperProps) {
    const [selectedFile, setSelectedFile] = useState<File | null>(props.selectedFile ?? null);
    const [selectedJob, setSelectedJob] = useState<JobResponse | null>(props.selectedJob ?? null);

    return (
        <ProcessView
            selectedFile={selectedFile}
            onFileSelect={(file) => {
                setSelectedFile(file);
                props.onFileSelect?.(file ?? null);
            }}
            isProcessing={props.isProcessing ?? false}
            progress={props.progress ?? 0}
            statusMessage={props.statusMessage ?? ''}
            error={props.error ?? ''}
            onStartProcessing={props.onStartProcessing ?? (async () => {})}
            onReset={() => {
                setSelectedFile(null);
                props.onReset?.();
            }}
            selectedJob={selectedJob}
            onJobSelect={(job) => {
                setSelectedJob(job);
                props.onJobSelect?.(job);
            }}
            recentJobs={props.recentJobs ?? []}
            jobsLoading={props.jobsLoading ?? false}
            statusStyles={props.statusStyles ?? statusStyles}
            formatDate={props.formatDate ?? formatDate}
            buildStaticUrl={props.buildStaticUrl ?? buildStaticUrl}
            onRefreshJobs={props.onRefreshJobs ?? (async () => {})}
        />
    );
}

function renderProcessView(props: WrapperProps = {}) {
    return render(
        <I18nProvider initialLocale="en">
            <ProcessViewWrapper {...props} />
        </I18nProvider>,
    );
}

type VideoMock = {
    trigger: (event: string) => void;
    restore: () => void;
};

function setupVideoMock({ width = 1080, height = 1920, duration = 2 }: { width?: number; height?: number; duration?: number } = {}): VideoMock {
    const realCreateElement = document.createElement.bind(document);
    const listeners: Record<string, Array<() => void>> = {};

    const videoStub: Partial<HTMLVideoElement> & Record<string, unknown> = {
        videoWidth: width,
        videoHeight: height,
        duration,
        muted: false,
        playsInline: false,
        preload: '',
        _src: '',
        set src(value: string) {
            this._src = value;
        },
        get src() {
            return this._src as string;
        },
        addEventListener: (type: string, cb: () => void) => {
            listeners[type] = listeners[type] || [];
            listeners[type].push(cb);
        },
        removeAttribute: jest.fn(),
        load: jest.fn(),
    };

    const createSpy = jest.spyOn(document, 'createElement');
    createSpy.mockImplementation((tagName: string, options?: ElementCreationOptions) => {
        if (tagName === 'video') {
            return videoStub as HTMLVideoElement;
        }
        return realCreateElement(tagName, options);
    });

    return {
        trigger: (event: string) => {
            (listeners[event] || []).forEach((fn) => fn());
        },
        restore: () => createSpy.mockRestore(),
    };
}

beforeAll(() => {
    // Canvas helpers needed for thumbnail generation path
    // @ts-expect-error jsdom does not implement getContext; provide a stub
    HTMLCanvasElement.prototype.getContext = jest.fn(() => ({
        drawImage: jest.fn(),
    }));
    // @ts-expect-error jsdom does not implement toDataURL; provide a stub
    HTMLCanvasElement.prototype.toDataURL = jest.fn(() => 'data:image/jpeg;base64,thumb');

    // Ensure requestAnimationFrame exists for modal animations
    // @ts-expect-error requestAnimationFrame is missing in jsdom by default
    global.requestAnimationFrame = (cb: FrameRequestCallback) => setTimeout(cb, 0);
});

beforeEach(() => {
    deleteJobMock.mockResolvedValue(undefined);
    // @ts-expect-error createObjectURL is missing in jsdom
    global.URL.createObjectURL = jest.fn(() => 'blob:mock');
    global.URL.revokeObjectURL = jest.fn();
});

afterEach(() => {
    jest.clearAllMocks();
});

it('generates and renders a thumbnail after loading video metadata', async () => {
    const videoMock = setupVideoMock();
    const file = new File(['video-bytes'], 'demo.mp4', { type: 'video/mp4' });

    const { container } = renderProcessView();
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;

    await act(async () => {
        fireEvent.change(fileInput, { target: { files: [file] } });
    });

    await act(async () => {
        videoMock.trigger('loadedmetadata');
        videoMock.trigger('seeked');
    });

    expect(await screen.findByAltText(/video thumbnail/i)).toBeInTheDocument();
    videoMock.restore();
});

it('clears preview and selection when deleting the currently selected job', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000);
    const job: JobResponse = {
        id: 'job-123',
        status: 'completed',
        progress: 100,
        message: 'Ready',
        created_at: nowSeconds,
        updated_at: nowSeconds,
        result_data: {
            original_filename: 'demo.mp4',
            public_url: 'https://example.com/video.mp4',
            video_path: 'https://example.com/video.mp4',
            model_size: 'medium',
            video_crf: 23,
            output_size: 10_000_000,
        },
    };

    const onJobSelect = jest.fn();
    const onRefreshJobs = jest.fn(async () => {});

    renderProcessView({
        recentJobs: [job],
        onJobSelect,
        onRefreshJobs,
    });

    fireEvent.click(await screen.findByRole('button', { name: /View/i }));
    expect(await screen.findByLabelText(/Close video/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '🗑️' }));
    fireEvent.click(screen.getByRole('button', { name: '✓' }));

    await waitFor(() => expect(deleteJobMock).toHaveBeenCalledWith(job.id));
    await waitFor(() => expect(onJobSelect).toHaveBeenLastCalledWith(null));
    await waitFor(() => expect(onRefreshJobs).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByLabelText(/Close video/i)).not.toBeInTheDocument());
});
