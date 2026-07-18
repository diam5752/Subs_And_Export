import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { PreviewSection } from '../PreviewSection';
import { useProcessContext } from '../../ProcessContext';
import { usePlaybackContext } from '../../PlaybackContext';

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('../../ProcessContext', () => ({
    useProcessContext: jest.fn(),
}));

jest.mock('../../PlaybackContext', () => ({
    usePlaybackContext: jest.fn(),
}));

jest.mock('@/components/PhoneFrame', () => ({
    PhoneFrame: ({ children }: { children: React.ReactNode }) => <div data-testid="phone-frame">{children}</div>,
}));

jest.mock('@/components/PreviewPlayer', () => ({
    PreviewPlayer: React.forwardRef(function MockPreviewPlayer(
        {
            videoUrl,
            cues,
            onTimeUpdate,
        }: {
            videoUrl: string;
            cues: Array<{ text: string }>;
            onTimeUpdate?: (time: number) => void;
        },
        ref,
    ) {
        void ref;
        return (
            <button type="button" data-testid="preview-player" onClick={() => onTimeUpdate?.(12.5)}>
                {videoUrl}:{cues.length}
            </button>
        );
    }),
}));

jest.mock('../Sidebar', () => ({
    Sidebar: () => <div data-testid="sidebar">sidebar</div>,
}));

jest.mock('../NewVideoConfirmModal', () => ({
    NewVideoConfirmModal: ({
        isOpen,
        onClose,
        onConfirm,
    }: {
        isOpen: boolean;
        onClose: () => void;
        onConfirm: () => void;
    }) => (
        isOpen ? (
            <div data-testid="new-video-modal">
                <button type="button" onClick={onConfirm}>confirm-new-video</button>
                <button type="button" onClick={onClose}>close-new-video</button>
            </div>
        ) : null
    ),
}));

jest.mock('@/components/VideoModal', () => ({
    VideoModal: ({
        isOpen,
        onClose,
    }: {
        isOpen: boolean;
        onClose: () => void;
    }) => (
        isOpen ? (
            <div data-testid="video-modal">
                <button type="button" onClick={onClose}>close-preview</button>
            </div>
        ) : null
    ),
}));

function buildContext() {
    return {
        selectedJob: null as {
            status: string;
            result_data?: {
                transcribe_provider?: string;
                model_size?: string;
            };
        } | null,
        isProcessing: false,
        transcribeProvider: 'groq',
        videoUrl: 'blob:video',
        processedCues: [{ start: 0, end: 1, text: 'hello' }],
        subtitlePosition: 20,
        subtitleColor: '#FFFF00',
        subtitleSize: 100,
        karaokeEnabled: true,
        maxSubtitleLines: 2,
        shadowStrength: 4,
        watermarkEnabled: true,
        playerRef: React.createRef(),
        resultsRef: React.createRef<HTMLDivElement>(),
        currentStep: 3,
        setOverrideStep: jest.fn(),
        AVAILABLE_MODELS: [
            {
                id: 'standard',
                provider: 'groq',
                mode: 'standard',
                name: 'Standard',
                icon: () => <span>model-icon</span>,
            },
            {
                id: 'pro',
                provider: 'groq',
                mode: 'pro',
                name: 'Pro',
                icon: () => <span>pro-icon</span>,
            },
        ],
        transcribeMode: 'standard',
        handleExport: jest.fn(async () => { }),
        exportingResolutions: {},
        exportError: null as string | null,
        onReset: jest.fn(),
        setHasChosenModel: jest.fn(),
        onJobSelect: jest.fn(),
    };
}

describe('PreviewSection', () => {
    const setCurrentTime = jest.fn();
    let contextValue: ReturnType<typeof buildContext>;

    beforeEach(() => {
        jest.clearAllMocks();
        contextValue = buildContext();
        (useProcessContext as jest.Mock).mockImplementation(() => contextValue);
        (usePlaybackContext as jest.Mock).mockReturnValue({ setCurrentTime });
        window.scrollTo = jest.fn();
    });

    it('shows the placeholder state when no completed job is available', () => {
        render(<PreviewSection />);

        expect(screen.getByText('resultPreviewTitle')).toBeInTheDocument();
        expect(screen.queryByTestId('preview-player')).not.toBeInTheDocument();
    });

    it('renders preview actions for completed jobs and forwards exports', () => {
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                model_size: 'standard',
            },
        };

        render(<PreviewSection />);

        fireEvent.click(screen.getByTestId('preview-player'));
        expect(setCurrentTime).toHaveBeenCalledWith(12.5);

        fireEvent.click(screen.getByTestId('srt-btn'));
        fireEvent.click(screen.getByTestId('vtt-btn'));
        fireEvent.click(screen.getByTestId('txt-btn'));
        fireEvent.click(screen.getByTestId('download-1080p-btn'));
        fireEvent.click(screen.getByTestId('download-4k-btn'));

        expect(contextValue.handleExport).toHaveBeenCalledWith('srt');
        expect(contextValue.handleExport).toHaveBeenCalledWith('vtt');
        expect(contextValue.handleExport).toHaveBeenCalledWith('txt');
        expect(contextValue.handleExport).toHaveBeenCalledWith('1080x1920');
        expect(contextValue.handleExport).toHaveBeenCalledWith('2160x3840');
        expect(screen.getByTestId('sidebar')).toBeInTheDocument();

        // REGRESSION: preview, controls, and exports must remain separate layout regions.
        expect(screen.getByTestId('completed-editor')).toBeInTheDocument();
        expect(screen.getByTestId('editor-preview-panel')).toBeInTheDocument();
        expect(document.querySelector('.editor-preview-meta')).not.toBeInTheDocument();
        expect(document.querySelector('.editor-model-pill')).not.toBeInTheDocument();
        expect(document.querySelector('.editor-aspect-pill')).not.toBeInTheDocument();

        // REGRESSION: video and subtitle downloads must be presented as two
        // distinct groups instead of one mixed row of formats.
        const videoExports = screen.getByTestId('video-export-group');
        const subtitleExports = screen.getByTestId('subtitle-export-group');
        expect(within(videoExports).getByText('exportVideoTitle')).toBeInTheDocument();
        expect(within(videoExports).getByTestId('download-1080p-btn')).toBeInTheDocument();
        expect(within(videoExports).getByTestId('download-4k-btn')).toBeInTheDocument();
        expect(within(videoExports).queryByTestId('srt-btn')).not.toBeInTheDocument();
        expect(within(subtitleExports).getByText('exportSubtitlesTitle')).toBeInTheDocument();
        expect(within(subtitleExports).getByTestId('srt-btn')).toBeInTheDocument();
        expect(within(subtitleExports).getByTestId('vtt-btn')).toBeInTheDocument();
        expect(within(subtitleExports).getByTestId('txt-btn')).toBeInTheDocument();
        expect(within(subtitleExports).queryByTestId('download-1080p-btn')).not.toBeInTheDocument();
    });

    it('renders export errors when the provider surfaces one', () => {
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                model_size: 'standard',
            },
        };
        contextValue.exportError = 'Export failed';

        render(<PreviewSection />);

        expect(screen.getByRole('alert')).toHaveTextContent('Export failed');
    });

    it('opens the new video flow and resets the workflow when confirmed', () => {
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                model_size: 'pro',
            },
        };

        render(<PreviewSection />);

        fireEvent.click(screen.getByRole('button', { name: 'newVideoButton' }));
        fireEvent.click(screen.getByRole('button', { name: 'confirm-new-video' }));

        expect(contextValue.onReset).toHaveBeenCalled();
        expect(contextValue.setHasChosenModel).toHaveBeenCalledWith(true);
        expect(contextValue.onJobSelect).toHaveBeenCalledWith(null);
        expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
    });

    it('does not repeat the workflow step heading inside the completed editor', () => {
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                model_size: 'standard',
            },
        };

        render(<PreviewSection />);

        // REGRESSION: workflow progress now has one canonical home above the editor.
        expect(screen.queryByText('step3Label')).not.toBeInTheDocument();
        expect(screen.getByTestId('completed-editor')).toBeInTheDocument();
    });
});
