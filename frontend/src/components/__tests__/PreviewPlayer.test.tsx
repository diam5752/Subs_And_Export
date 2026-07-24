/* eslint-disable @next/next/no-img-element */
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { PreviewPlayer, type PreviewPlayerHandle } from '@/components/PreviewPlayer';

jest.mock('next/image', () => ({
    __esModule: true,
    default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => <img {...props} alt={props.alt ?? ''} />,
}));

function mockResizeObserver() {
    if (typeof window.ResizeObserver !== 'undefined') return;
    class ResizeObserverMock {
        observe() { }
        unobserve() { }
        disconnect() { }
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).ResizeObserver = ResizeObserverMock;
}

describe('PreviewPlayer', () => {
    beforeAll(() => {
        mockResizeObserver();
        Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
            configurable: true,
            value: jest.fn().mockResolvedValue(undefined),
        });
        Object.defineProperty(window.HTMLMediaElement.prototype, 'pause', {
            configurable: true,
            value: jest.fn(),
        });
    });

    afterEach(() => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        delete (HTMLVideoElement.prototype as any).requestVideoFrameCallback;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        delete (HTMLVideoElement.prototype as any).cancelVideoFrameCallback;
        jest.restoreAllMocks();
    });

    const baseProps = {
        videoUrl: 'blob:test',
        cues: [],
        settings: {
            position: 20,
            color: '#FFFF00',
            fontSize: 100,
            karaoke: true,
            maxLines: 2,
            shadowStrength: 4,
        },
    };

    it('uses requestVideoFrameCallback for high-res time sync when available', () => {
        const requestVideoFrameCallback = jest.fn().mockReturnValue(123);
        const cancelVideoFrameCallback = jest.fn();

        Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', {
            value: requestVideoFrameCallback,
            configurable: true,
        });
        Object.defineProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback', {
            value: cancelVideoFrameCallback,
            configurable: true,
        });

        const { container, unmount } = render(<PreviewPlayer {...baseProps} />);
        const video = container.querySelector('video');
        expect(video).not.toBeNull();

        fireEvent.play(video as HTMLVideoElement);
        expect(requestVideoFrameCallback).toHaveBeenCalledTimes(1);

        unmount();
        expect(cancelVideoFrameCallback).toHaveBeenCalledWith(123);
    });

    it('falls back to requestAnimationFrame when requestVideoFrameCallback is unavailable', () => {
        const requestAnimationFrameSpy = jest.spyOn(window, 'requestAnimationFrame').mockReturnValue(456);
        const cancelAnimationFrameSpy = jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => { });

        const { container, unmount } = render(<PreviewPlayer {...baseProps} />);
        const video = container.querySelector('video');
        expect(video).not.toBeNull();

        fireEvent.play(video as HTMLVideoElement);
        expect(requestAnimationFrameSpy).toHaveBeenCalledTimes(1);

        unmount();
        expect(cancelAnimationFrameSpy).toHaveBeenCalledWith(456);
    });

    it('renders the watermark and reports time updates', async () => {
        const onTimeUpdate = jest.fn();
        const { container } = render(
            <PreviewPlayer
                {...baseProps}
                settings={{ ...baseProps.settings, watermarkEnabled: true }}
                onTimeUpdate={onTimeUpdate}
            />,
        );

        expect(screen.getByAltText('Watermark')).toBeInTheDocument();

        const video = container.querySelector('video') as HTMLVideoElement;
        Object.defineProperty(video, 'currentTime', {
            configurable: true,
            value: 4.2,
            writable: true,
        });

        fireEvent.timeUpdate(video);

        await waitFor(() => {
            expect(onTimeUpdate).toHaveBeenCalledWith(4.2);
        });
    });

    it('seeks through the imperative handle and applies initial time on metadata load', () => {
        const playerRef = React.createRef<PreviewPlayerHandle>();
        const { container } = render(
            <PreviewPlayer
                {...baseProps}
                ref={playerRef}
                initialTime={2}
            />,
        );

        const video = container.querySelector('video') as HTMLVideoElement;
        Object.defineProperty(video, 'currentTime', {
            configurable: true,
            value: 0,
            writable: true,
        });

        fireEvent.loadedMetadata(video);
        expect(video.currentTime).toBeCloseTo(2, 4);

        act(() => {
            playerRef.current?.seekTo(7.5);
        });
        expect(video.currentTime).toBeCloseTo(7.5, 4);

        act(() => {
            playerRef.current?.pause();
        });
        expect(video.pause).toHaveBeenCalled();
    });

    it('pauses playback and maps the visible subtitle to its editable source cue', () => {
        const onBeginEdit = jest.fn();
        const cue = {
            start: 0,
            end: 2,
            text: 'editable subtitle',
            words: [
                { start: 0, end: 1, text: 'editable' },
                { start: 1, end: 2, text: 'subtitle' },
            ],
        };

        const { container } = render(
            <PreviewPlayer
                {...baseProps}
                cues={[cue]}
                subtitleEditor={{
                    cues: [cue],
                    editingCueIndex: null,
                    draftText: '',
                    isSaving: false,
                    labels: {
                        editAction: 'Edit active subtitle',
                        title: 'Edit subtitle',
                        textarea: 'Subtitle text',
                        save: 'Save',
                        cancel: 'Cancel',
                        shortcut: 'Ctrl+Enter to save',
                        saving: 'Saving…',
                    },
                    onBeginEdit,
                    onChange: jest.fn(),
                    onSave: jest.fn(),
                    onCancel: jest.fn(),
                }}
            />,
        );

        const video = container.querySelector('video') as HTMLVideoElement;
        fireEvent.click(screen.getByRole('button', { name: 'Edit active subtitle' }));

        expect(video.pause).toHaveBeenCalled();
        expect(onBeginEdit).toHaveBeenCalledWith(0);
    });

    it('pauses playback before direct subtitle positioning', () => {
        // REGRESSION: the active cue must not disappear while the user is
        // dragging it on the preview.
        const onPositionChange = jest.fn();
        const { container } = render(
            <PreviewPlayer
                {...baseProps}
                cues={[{ start: 0, end: 2, text: 'move me' }]}
                subtitleTransformControls={{
                    labels: {
                        move: 'Move subtitles',
                        resize: 'Resize subtitles',
                    },
                    onPositionChange,
                    onSizeChange: jest.fn(),
                }}
            />,
        );

        const video = container.querySelector('video') as HTMLVideoElement;
        const overlay = screen.getByTestId('subtitle-overlay');
        fireEvent.pointerDown(overlay, {
            button: 0,
            pointerId: 10,
            clientX: 300,
            clientY: 900,
        });
        fireEvent.pointerMove(overlay, {
            pointerId: 10,
            clientX: 300,
            clientY: 800,
        });

        expect(video.pause).toHaveBeenCalled();
        expect(onPositionChange).toHaveBeenCalled();
    });
});
