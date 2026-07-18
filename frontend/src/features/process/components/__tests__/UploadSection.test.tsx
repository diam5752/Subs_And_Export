/* eslint-disable @next/next/no-img-element */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { UploadSection } from '../UploadSection';
import { useProcessContext } from '../../ProcessContext';
import { validateVideoAspectRatio } from '@/lib/video';

jest.mock('next/image', () => ({
    __esModule: true,
    default: (allProps: React.ImgHTMLAttributes<HTMLImageElement> & {
        fill?: boolean;
        unoptimized?: boolean;
        sizes?: string;
    }) => {
        const props = { ...allProps };
        delete props.fill;
        delete props.unoptimized;
        delete props.sizes;
        return <img {...props} alt={props.alt ?? ''} />;
    },
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('../../ProcessContext', () => ({
    useProcessContext: jest.fn(),
}));

jest.mock('@/lib/video', () => ({
    validateVideoAspectRatio: jest.fn(),
}));

type MockContext = ReturnType<typeof buildContext>;

const sampleModel = {
    id: 'standard',
    provider: 'groq',
    mode: 'standard',
    name: 'Standard',
    icon: () => <span>model-icon</span>,
};

function buildContext() {
    return {
        selectedFile: null as File | null,
        onFileSelect: jest.fn(),
        isProcessing: false,
        hasChosenModel: true,
        transcribeProvider: 'groq',
        transcribeMode: 'standard',
        AVAILABLE_MODELS: [sampleModel],
        currentStep: 2,
        setOverrideStep: jest.fn(),
        setHasChosenModel: jest.fn(),
        onJobSelect: jest.fn(),
        handleStart: jest.fn(),
        fileInputRef: React.createRef<HTMLInputElement>(),
        resultsRef: React.createRef<HTMLDivElement>(),
        videoInfo: null as {
            width: number;
            height: number;
            aspectWarning: boolean;
            thumbnailUrl: string | null;
            durationSeconds: number;
        } | null,
        setVideoInfo: jest.fn(),
        setPreviewVideoUrl: jest.fn(),
        setCues: jest.fn(),
        selectedJob: null as {
            status: string;
            result_data?: {
                transcribe_provider?: string;
                model_size?: string;
                original_filename?: string | null;
                output_size?: number;
                files_missing?: boolean;
            };
        } | null,
        error: '',
        progress: 0,
        statusMessage: '',
        onCancelProcessing: jest.fn(),
        videoUrl: null as string | null,
    };
}

describe('UploadSection', () => {
    let contextValue: MockContext;

    beforeEach(() => {
        jest.clearAllMocks();
        jest.useFakeTimers();
        contextValue = buildContext();
        (useProcessContext as jest.Mock).mockImplementation(() => contextValue);
        (validateVideoAspectRatio as jest.Mock).mockResolvedValue({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb',
            durationSeconds: 12,
        });
        Object.defineProperty(window.URL, 'createObjectURL', {
            writable: true,
            value: jest.fn(() => 'blob:preview'),
        });
        Object.defineProperty(window.URL, 'revokeObjectURL', {
            writable: true,
            value: jest.fn(),
        });
        window.HTMLElement.prototype.scrollIntoView = jest.fn();
        contextValue.resultsRef.current = {
            scrollIntoView: jest.fn(),
        } as unknown as HTMLDivElement;
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    function renderUpload() {
        return render(<UploadSection />);
    }

    it('shows the locked state until a model is chosen', () => {
        contextValue.hasChosenModel = false;

        renderUpload();

        expect(screen.getByText('uploadEngineRequired')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'uploadDropTitle' })).toHaveAttribute('aria-disabled', 'true');
    });

    it('shows an error when the video duration cannot be read', async () => {
        contextValue.selectedFile = new File(['video'], 'broken.mp4', { type: 'video/mp4' });
        (validateVideoAspectRatio as jest.Mock).mockResolvedValueOnce({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb',
            durationSeconds: 0,
        });

        renderUpload();

        await waitFor(() => {
            expect(screen.getByText('uploadDurationUnreadable')).toBeInTheDocument();
        });
        expect(contextValue.setPreviewVideoUrl).toHaveBeenCalledWith('blob:preview');
        expect(contextValue.setCues).toHaveBeenCalledWith([]);
    });

    it('shows an error when the selected video is too long', async () => {
        contextValue.selectedFile = new File(['video'], 'long.mp4', { type: 'video/mp4' });
        (validateVideoAspectRatio as jest.Mock).mockResolvedValueOnce({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb',
            durationSeconds: 500,
        });

        renderUpload();

        await waitFor(() => {
            expect(screen.getByText('uploadDurationTooLong')).toBeInTheDocument();
        });
    });

    it('keeps a valid upload ready until the user explicitly starts processing', async () => {
        const file = new File(['video'], 'clip.mp4', { type: 'video/mp4' });
        const { container, rerender } = renderUpload();
        const input = container.querySelector('input[type="file"]') as HTMLInputElement;

        fireEvent.change(input, {
            target: {
                files: [file],
            },
        });

        expect(contextValue.onFileSelect).toHaveBeenCalledWith(file);

        contextValue.selectedFile = file;
        contextValue.videoInfo = {
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb',
            durationSeconds: 12,
        };

        rerender(<UploadSection />);

        await waitFor(() => {
            expect(contextValue.setPreviewVideoUrl).toHaveBeenCalledWith('blob:preview');
        });
        expect(contextValue.handleStart).not.toHaveBeenCalled();
    });

    it('handles drag-and-drop uploads and unlock-step reset', () => {
        const { getByRole } = renderUpload();

        fireEvent.drop(getByRole('button', { name: 'uploadDropTitle' }), {
            dataTransfer: {
                files: [new File(['video'], 'drop.mp4', { type: 'video/mp4' })],
            },
        });

        expect(contextValue.onFileSelect).toHaveBeenCalledWith(expect.objectContaining({ name: 'drop.mp4' }));
        expect(contextValue.setOverrideStep).toHaveBeenCalledWith(null);
    });

    it('rejects files above the configured upload ceiling before processing', () => {
        const oversized = new File(['video'], 'oversized.mp4', { type: 'video/mp4' });
        Object.defineProperty(oversized, 'size', { value: 1024 * 1024 * 1024 + 1 });
        const { container } = renderUpload();
        const input = container.querySelector('input[type="file"]') as HTMLInputElement;

        fireEvent.change(input, { target: { files: [oversized] } });

        expect(screen.getByText('uploadFileTooLarge')).toBeInTheDocument();
        expect(contextValue.onFileSelect).not.toHaveBeenCalled();
    });

    it('keeps the input summary aligned with Step 1 without a stale nested step label', () => {
        contextValue.currentStep = 1;
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                model_size: 'standard',
                original_filename: 'finished.mp4',
                output_size: 2048,
            },
        };

        renderUpload();

        // REGRESSION: the old upload card said "STEP 2 / Upload Video" while
        // the single source-of-truth workflow indicator correctly showed Step 1.
        expect(screen.getByRole('heading', { name: 'inputVideoTitle' })).toBeInTheDocument();
        expect(screen.queryByText(/STEP 2/i)).not.toBeInTheDocument();
        expect(screen.queryByText('Upload Video')).not.toBeInTheDocument();
        expect(screen.queryByText('localDemoLabel')).not.toBeInTheDocument();
        expect(screen.queryByText('sampleVideoTitle')).not.toBeInTheDocument();

        const summaryToggle = screen.getByRole('button', { name: 'inputVideoSummaryToggle' });
        const details = screen.getByTestId('input-video-details');
        expect(summaryToggle).toHaveAttribute('aria-expanded', 'false');
        expect(details).toHaveAttribute('aria-hidden', 'true');
        expect(details).toHaveAttribute('inert');
        fireEvent.click(summaryToggle);
        expect(summaryToggle).toHaveAttribute('aria-expanded', 'true');
        expect(details).toHaveAttribute('aria-hidden', 'false');
        expect(details).not.toHaveAttribute('inert');
        expect(contextValue.setOverrideStep).not.toHaveBeenCalled();
    });

    it('shows compact completed state actions for matched jobs', () => {
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                model_size: 'standard',
                original_filename: 'finished.mp4',
                output_size: 2048,
            },
        };

        renderUpload();

        fireEvent.click(screen.getByRole('button', { name: 'viewResults' }));

        expect(contextValue.setOverrideStep).toHaveBeenCalledWith(3);
    });

    it('shows reprocess and reset actions when the selected tier does not match the completed job', () => {
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                model_size: 'pro',
                original_filename: 'finished.mp4',
                output_size: 2048,
            },
        };

        renderUpload();

        fireEvent.click(screen.getByRole('button', { name: /startProcessing/i }));
        expect(contextValue.handleStart).toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'uploadNew' }));
        expect(contextValue.onFileSelect).toHaveBeenCalledWith(null);
        expect(contextValue.onJobSelect).toHaveBeenCalledWith(null);
        expect(contextValue.setHasChosenModel).toHaveBeenCalledWith(true);
    });
});
