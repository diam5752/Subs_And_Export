/* eslint-disable @next/next/no-img-element */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

function buildContext() {
    return {
        selectedFile: null as File | null,
        onFileSelect: jest.fn(),
        isProcessing: false,
        currentStep: 2,
        setOverrideStep: jest.fn(),
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
                transcribe_tier?: string;
                original_filename?: string | null;
                output_size?: number;
                files_missing?: boolean;
                duration_seconds?: number;
            };
        } | null,
        error: '',
        progress: 0,
        statusMessage: '',
        onCancelProcessing: jest.fn(),
        videoUrl: null as string | null,
        transcribeMode: 'standard' as 'standard' | 'pro',
        transcribeProvider: 'mock' as 'mock' | 'elevenlabs' | 'groq' | 'local',
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
            durationSeconds: 181,
        });

        renderUpload();

        await waitFor(() => {
            expect(screen.getByText('uploadDurationTooLong')).toBeInTheDocument();
        });
    });

    it('accepts a video at the three-minute launch limit', async () => {
        contextValue.selectedFile = new File(['video'], 'three-minute-clip.mp4', { type: 'video/mp4' });
        (validateVideoAspectRatio as jest.Mock).mockResolvedValueOnce({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb',
            durationSeconds: 180,
        });

        renderUpload();

        await waitFor(() => {
            expect(contextValue.setVideoInfo).toHaveBeenCalledWith(expect.objectContaining({ durationSeconds: 180 }));
        });
        expect(screen.queryByText('uploadDurationTooLong')).not.toBeInTheDocument();
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

    it('keeps processing disabled until the selected file validation settles', async () => {
        contextValue.selectedFile = new File(['video'], 'delayed.mp4', { type: 'video/mp4' });
        let resolveValidation!: (info: {
            width: number;
            height: number;
            aspectWarning: boolean;
            thumbnailUrl: string | null;
            durationSeconds: number;
        }) => void;
        (validateVideoAspectRatio as jest.Mock).mockReturnValueOnce(new Promise((resolve) => {
            resolveValidation = resolve;
        }));

        renderUpload();

        const startButton = screen.getByRole('button', { name: /startProcessing/i });
        expect(startButton).toBeDisabled();
        expect(startButton).toHaveAttribute('aria-busy', 'true');
        fireEvent.click(startButton);
        expect(contextValue.handleStart).not.toHaveBeenCalled();

        await act(async () => {
            resolveValidation({
                width: 1080,
                height: 1920,
                aspectWarning: false,
                thumbnailUrl: 'blob:thumb',
                durationSeconds: 8.633333,
            });
            await Promise.resolve();
        });

        expect(startButton).toBeEnabled();
        expect(startButton).not.toHaveAttribute('aria-busy');
        fireEvent.click(startButton);
        expect(contextValue.handleStart).toHaveBeenCalledTimes(1);
    });

    it('does not reopen a settled same-file validation when context callbacks change', async () => {
        // REGRESSION: effect dependencies unrelated to the File identity could
        // restart validation, clear a hard error, and briefly re-enable Start
        // with no authoritative duration or quote.
        contextValue.selectedFile = new File(['video'], 'too-long.mp4', { type: 'video/mp4' });
        (validateVideoAspectRatio as jest.Mock).mockResolvedValueOnce({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb',
            durationSeconds: 601,
        });
        const view = renderUpload();

        const startButton = screen.getByRole('button', { name: /startProcessing/i });
        await waitFor(() => {
            expect(screen.getAllByText('uploadDurationTooLong').length).toBeGreaterThan(0);
            expect(startButton).toBeDisabled();
        });
        expect(validateVideoAspectRatio).toHaveBeenCalledTimes(1);

        contextValue.setCues = jest.fn();
        view.rerender(<UploadSection />);

        expect(validateVideoAspectRatio).toHaveBeenCalledTimes(1);
        expect(startButton).toBeDisabled();
        expect(screen.getAllByText('uploadDurationTooLong').length).toBeGreaterThan(0);
    });

    it('aborts stale metadata validation when the selected file changes', () => {
        contextValue.selectedFile = new File(['first'], 'first.mp4', { type: 'video/mp4' });
        (validateVideoAspectRatio as jest.Mock).mockReturnValue(new Promise(() => undefined));
        const view = renderUpload();
        const firstSignal = (validateVideoAspectRatio as jest.Mock).mock.calls[0][1] as AbortSignal;
        expect(firstSignal.aborted).toBe(false);

        contextValue.selectedFile = new File(['second'], 'second.mp4', { type: 'video/mp4' });
        view.rerender(<UploadSection />);

        expect(firstSignal.aborted).toBe(true);
        expect(validateVideoAspectRatio).toHaveBeenCalledTimes(2);
        expect((validateVideoAspectRatio as jest.Mock).mock.calls[1][1]).toBeInstanceOf(AbortSignal);
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

    it('accepts a file at the 500 MB upload ceiling', () => {
        const atLimit = new File(['video'], 'at-limit.mp4', { type: 'video/mp4' });
        Object.defineProperty(atLimit, 'size', { value: 500 * 1024 * 1024 });
        const { container } = renderUpload();
        const input = container.querySelector('input[type="file"]') as HTMLInputElement;

        fireEvent.change(input, { target: { files: [atLimit] } });

        expect(screen.queryByText('uploadFileTooLarge')).not.toBeInTheDocument();
        expect(contextValue.onFileSelect).toHaveBeenCalledWith(atLimit);
    });

    it('explains the temporary workspace before the user uploads', () => {
        renderUpload();

        // REGRESSION: users were not told that every upload and export shares
        // one auto-deleting workspace whose timer refreshes after activity.
        expect(screen.getByText('temporaryWorkspaceUploadNote')).toBeInTheDocument();
    });

    it('rejects files above the 500 MB upload ceiling before processing', () => {
        const oversized = new File(['video'], 'oversized.mp4', { type: 'video/mp4' });
        Object.defineProperty(oversized, 'size', { value: 500 * 1024 * 1024 + 1 });
        const { container } = renderUpload();
        const input = container.querySelector('input[type="file"]') as HTMLInputElement;

        fireEvent.change(input, { target: { files: [oversized] } });

        // REGRESSION: the public release previously rejected files above 95 MB.
        expect(screen.getByText('uploadFileTooLarge')).toBeInTheDocument();
        expect(contextValue.onFileSelect).not.toHaveBeenCalled();
    });

    it('keeps the input summary aligned with Step 1 without a stale nested step label', () => {
        contextValue.currentStep = 1;
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                transcribe_tier: 'standard',
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
                transcribe_tier: 'standard',
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
                transcribe_tier: 'pro',
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
    });

    it('uses duration pricing regardless of provider and recognizes a matching pro job', () => {
        contextValue.transcribeMode = 'pro';
        contextValue.transcribeProvider = 'elevenlabs';
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                transcribe_tier: 'standard',
                original_filename: 'standard.mp4',
                output_size: 2048,
                duration_seconds: 180,
            },
        };

        const { rerender } = renderUpload();
        expect(screen.getByRole('button', { name: /startProcessing 30/i })).toBeInTheDocument();

        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'elevenlabs',
                transcribe_tier: 'pro',
                original_filename: 'scribe.mp4',
                output_size: 2048,
            },
        };
        rerender(<UploadSection />);

        expect(screen.getByRole('button', { name: 'viewResults' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /startProcessing/i })).not.toBeInTheDocument();
    });

    it('keeps 3 minutes active and marks the larger launch tiers as coming soon', async () => {
        contextValue.selectedFile = new File(['video'], 'priced.mp4', { type: 'video/mp4' });
        contextValue.videoInfo = {
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: null,
            durationSeconds: 120,
        };

        renderUpload();

        const pricing = screen.getByTestId('video-credit-pricing');
        expect(pricing).toHaveTextContent('30 creditsLabel');
        expect(within(pricing).getAllByText('videoCreditPricingComingSoon')).toHaveLength(2);
        expect(pricing.querySelectorAll('[data-available="false"]')).toHaveLength(2);
        expect(pricing.querySelector('[data-active="true"]')).toHaveTextContent('30 creditsLabel');
        const startButton = screen.getByRole('button', { name: /startProcessing 30/i });
        await waitFor(() => {
            expect(startButton).toBeEnabled();
        });
    });
});
