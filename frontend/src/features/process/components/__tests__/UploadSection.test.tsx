/* eslint-disable @next/next/no-img-element */
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { UploadSection } from '../UploadSection';
import { useProcessContext } from '../../ProcessContext';
import { useAppEnv } from '@/context/AppEnvContext';
import { api } from '@/lib/api';
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

jest.mock('@/context/AppEnvContext', () => ({
    useAppEnv: jest.fn(),
}));

jest.mock('../../ProcessContext', () => ({
    useProcessContext: jest.fn(),
}));

jest.mock('@/lib/api', () => ({
    api: {
        loadDevSampleJob: jest.fn(),
    },
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
        (useAppEnv as jest.Mock).mockReturnValue({ appEnv: 'prod' });
        (validateVideoAspectRatio as jest.Mock).mockResolvedValue({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb',
            durationSeconds: 12,
        });
        (api.loadDevSampleJob as jest.Mock).mockResolvedValue({
            id: 'sample-job',
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                model_size: 'standard',
            },
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

        expect(screen.getByText('Select a model above to unlock')).toBeInTheDocument();
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
            expect(screen.getByText('Could not read video duration. Please try another file.')).toBeInTheDocument();
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
            expect(screen.getByText('Video too long. Maximum allowed duration is 3 minutes.')).toBeInTheDocument();
        });
    });

    it('auto-starts after a valid file is selected and validated', async () => {
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
            expect(contextValue.handleStart).toHaveBeenCalled();
        });
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

    it('loads a dev sample and surfaces backend detail errors', async () => {
        const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => { });
        (useAppEnv as jest.Mock).mockReturnValue({ appEnv: 'dev' });
        (api.loadDevSampleJob as jest.Mock)
            .mockResolvedValueOnce({
                id: 'sample-job',
                status: 'completed',
                result_data: { transcribe_provider: 'groq', model_size: 'standard' },
            })
            .mockRejectedValueOnce({
                response: { data: { detail: 'backend sample failed' } },
            });

        renderUpload();

        fireEvent.click(screen.getByRole('button', { name: 'Load sample video' }));

        await waitFor(() => {
            expect(api.loadDevSampleJob).toHaveBeenCalledWith('groq', 'standard');
            expect(contextValue.setHasChosenModel).toHaveBeenCalledWith(true);
            expect(contextValue.onJobSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'sample-job' }));
        });

        act(() => {
            jest.advanceTimersByTime(100);
        });
        expect(contextValue.resultsRef.current?.scrollIntoView).toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Load sample video' }));

        await waitFor(() => {
            expect(screen.getByText('backend sample failed')).toBeInTheDocument();
        });
        expect(errorSpy).toHaveBeenCalledWith('Failed to load dev sample:', {
            response: { data: { detail: 'backend sample failed' } },
        });
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

        fireEvent.click(screen.getByRole('button', { name: /View Results/i }));

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
