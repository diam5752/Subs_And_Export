import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { formatPlaybackTime, PreviewSection } from '../PreviewSection';
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
            onPlaybackStatusChange,
            subtitleEditor,
            subtitleTransformControls,
        }: {
            videoUrl: string;
            cues: Array<{ text: string }>;
            onTimeUpdate?: (time: number) => void;
            onPlaybackStatusChange?: (status: {
                duration: number;
                isPlaying: boolean;
                isMuted: boolean;
            }) => void;
            subtitleEditor?: {
                cues: Array<{ text: string }>;
                onBeginEdit: (index: number) => void;
            };
            subtitleTransformControls?: {
                onPositionChange: (position: number) => void;
                onSizeChange: (size: number) => void;
            };
        },
        ref,
    ) {
        React.useImperativeHandle(ref, () => ({
            seekTo: mockSeekTo,
            pause: jest.fn(),
            togglePlayback: mockTogglePlayback,
            toggleMuted: mockToggleMuted,
        }));
        return (
            <div>
                <button type="button" data-testid="preview-player" onClick={() => onTimeUpdate?.(12.5)}>
                    {videoUrl}:{cues.length}
                </button>
                <button
                    type="button"
                    data-testid="inline-editor-bridge"
                    data-source-cues={subtitleEditor?.cues.length ?? 0}
                    onClick={() => subtitleEditor?.onBeginEdit(0)}
                >
                    edit-on-video
                </button>
                <button
                    type="button"
                    data-testid="position-on-video"
                    onClick={() => subtitleTransformControls?.onPositionChange(42)}
                >
                    position-on-video
                </button>
                <button
                    type="button"
                    data-testid="resize-on-video"
                    onClick={() => subtitleTransformControls?.onSizeChange(115)}
                >
                    resize-on-video
                </button>
                <button
                    type="button"
                    data-testid="playback-status-bridge"
                    onClick={() => onPlaybackStatusChange?.({
                        duration: 30,
                        isPlaying: true,
                        isMuted: false,
                    })}
                >
                    playback-status
                </button>
            </div>
        );
    }),
}));

const mockSeekTo = jest.fn();
const mockTogglePlayback = jest.fn();
const mockToggleMuted = jest.fn();

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
                transcribe_tier?: string;
            };
        } | null,
        isProcessing: false,
        videoUrl: 'blob:video',
        processedCues: [{ start: 0, end: 1, text: 'hello' }],
        cues: [{ start: 0, end: 1, text: 'hello' }],
        subtitlePosition: 20,
        setSubtitlePosition: jest.fn(),
        subtitleColor: '#FFFF00',
        subtitleSize: 100,
        setSubtitleSize: jest.fn(),
        karaokeEnabled: true,
        maxSubtitleLines: 2,
        shadowStrength: 4,
        watermarkEnabled: true,
        playerRef: React.createRef(),
        resultsRef: React.createRef<HTMLDivElement>(),
        currentStep: 3,
        setOverrideStep: jest.fn(),
        handleExport: jest.fn(async () => { }),
        exportingResolutions: {},
        exportError: null as string | null,
        onReset: jest.fn(),
        onJobSelect: jest.fn(),
        editingCueIndex: null as number | null,
        editingCueDraft: '',
        editingCueSurface: null as 'video' | 'transcript' | null,
        isSavingTranscript: false,
        beginEditingCue: jest.fn(),
        handleUpdateDraft: jest.fn(),
        saveEditingCue: jest.fn(async () => { }),
        cancelEditingCue: jest.fn(),
    };
}

describe('PreviewSection', () => {
    const setCurrentTime = jest.fn();
    let contextValue: ReturnType<typeof buildContext>;

    beforeEach(() => {
        jest.clearAllMocks();
        contextValue = buildContext();
        (useProcessContext as jest.Mock).mockImplementation(() => contextValue);
        (usePlaybackContext as jest.Mock).mockReturnValue({ currentTime: 0, setCurrentTime });
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
                transcribe_tier: 'standard',
            },
        };

        render(<PreviewSection />);

        fireEvent.click(screen.getByTestId('preview-player'));
        expect(setCurrentTime).toHaveBeenCalledWith(12.5);

        const inlineEditorBridge = screen.getByTestId('inline-editor-bridge');
        expect(inlineEditorBridge).toHaveAttribute('data-source-cues', '1');
        fireEvent.click(inlineEditorBridge);
        expect(contextValue.beginEditingCue).toHaveBeenCalledWith(0, 'video');

        fireEvent.click(screen.getByTestId('position-on-video'));
        fireEvent.click(screen.getByTestId('resize-on-video'));
        expect(contextValue.setSubtitlePosition).toHaveBeenCalledWith(42);
        expect(contextValue.setSubtitleSize).toHaveBeenCalledWith(115);
        expect(screen.getByText('subtitleDirectManipulationHint')).toBeInTheDocument();

        // REGRESSION: playback controls must live outside the phone viewport so
        // mobile browser chrome can never cover editable subtitles.
        const playbackControls = screen.getByTestId('editor-preview-controls');
        fireEvent.click(within(playbackControls).getByRole('button', { name: 'playPreview' }));
        expect(mockTogglePlayback).toHaveBeenCalledTimes(1);
        fireEvent.click(within(playbackControls).getByRole('button', { name: 'mutePreview' }));
        expect(mockToggleMuted).toHaveBeenCalledTimes(1);
        fireEvent.click(screen.getByTestId('playback-status-bridge'));
        expect(within(playbackControls).getByRole('button', { name: 'pausePreview' })).toBeInTheDocument();
        expect(screen.getByTestId('editor-preview-time')).toHaveTextContent('0:00 / 0:30');
        expect(screen.getByTestId('subtitle-touch-manipulation-hint')).toHaveTextContent(
            'subtitleTouchManipulationHint',
        );
        fireEvent.change(within(playbackControls).getByRole('slider', { name: 'seekVideo' }), {
            target: { value: '7.5' },
        });
        expect(mockSeekTo).toHaveBeenCalledWith(7.5);
        expect(setCurrentTime).toHaveBeenCalledWith(7.5);

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
        // REGRESSION: exporting used to give no indication that it refreshes
        // the project's automatic deletion window.
        expect(screen.getByText('temporaryWorkspaceExportNote')).toBeInTheDocument();
    });

    it('renders export errors when the provider surfaces one', () => {
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                transcribe_tier: 'standard',
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
                transcribe_tier: 'pro',
            },
        };

        render(<PreviewSection />);

        fireEvent.click(screen.getByRole('button', { name: 'newVideoButton' }));
        fireEvent.click(screen.getByRole('button', { name: 'confirm-new-video' }));

        expect(contextValue.onReset).toHaveBeenCalled();
        expect(contextValue.onJobSelect).toHaveBeenCalledWith(null);
        expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
    });

    it('does not repeat the workflow step heading inside the completed editor', () => {
        contextValue.selectedJob = {
            status: 'completed',
            result_data: {
                transcribe_provider: 'groq',
                transcribe_tier: 'standard',
            },
        };

        render(<PreviewSection />);

        // REGRESSION: workflow progress now has one canonical home above the editor.
        expect(screen.queryByText('step3Label')).not.toBeInTheDocument();
        expect(screen.getByTestId('completed-editor')).toBeInTheDocument();
    });
});

describe('formatPlaybackTime', () => {
    it('formats safe minute and hour timestamps for the compact player', () => {
        expect(formatPlaybackTime(0)).toBe('0:00');
        expect(formatPlaybackTime(65.9)).toBe('1:05');
        expect(formatPlaybackTime(3661)).toBe('1:01:01');
        expect(formatPlaybackTime(Number.NaN)).toBe('0:00');
        expect(formatPlaybackTime(-4)).toBe('0:00');
    });
});
