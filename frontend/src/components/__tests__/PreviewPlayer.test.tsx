import React from 'react';
import { fireEvent, render } from '@testing-library/react';
import '@testing-library/jest-dom';
import { PreviewPlayer } from '@/components/PreviewPlayer';

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
});

