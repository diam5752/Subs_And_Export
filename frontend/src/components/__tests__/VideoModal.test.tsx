
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { VideoModal } from '../VideoModal';
import '@testing-library/jest-dom';

describe('VideoModal', () => {
    const defaultProps = {
        isOpen: true,
        onClose: jest.fn(),
        videoUrl: 'http://example.com/video.mp4',
    };

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('should result null when closed', () => {
        const { container } = render(<VideoModal {...defaultProps} isOpen={false} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('should result null when no video url', () => {
        const { container } = render(<VideoModal {...defaultProps} videoUrl="" />);
        expect(container).toBeEmptyDOMElement();
    });

    it('should render video when open', () => {
        const { container } = render(<VideoModal {...defaultProps} />);
        const videoElement = container.querySelector('video');
        expect(videoElement).toBeInTheDocument();
        expect(videoElement).toHaveAttribute('src', 'http://example.com/video.mp4');

        const videoContainer = container.querySelector('.video-container-glow');
        expect(videoContainer).toHaveClass('aspect-[9/16]');
    });

    it('should close on backdrop click', () => {
        render(<VideoModal {...defaultProps} />);
        // The outer div is the backdrop
        // Looking at structure:
        // <div onClick={onClose}> ... <div onClick={stopPropagation}> <video> ...

        // Trigger click on outer div. We can find it by text or structure.
        // It has text "Click outside or press ESC to close"
        const backdrop = screen.getByText(/Click outside/i).closest('.fixed');
        fireEvent.click(backdrop!);
        expect(defaultProps.onClose).toHaveBeenCalled();
    });

    it('should NOT close on content click', () => {
        render(<VideoModal {...defaultProps} />);
        const videoContainer = document.querySelector('.video-container-glow');
        fireEvent.click(videoContainer!);
        expect(defaultProps.onClose).not.toHaveBeenCalled();
    });

    it('should close on Escape key', () => {
        render(<VideoModal {...defaultProps} />);
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(defaultProps.onClose).toHaveBeenCalled();
    });

    it('should close on close button click', () => {
        render(<VideoModal {...defaultProps} />);
        fireEvent.click(screen.getByLabelText('Close video'));
        expect(defaultProps.onClose).toHaveBeenCalled();
    });

    it('should manage body overflow', () => {
        const { unmount } = render(<VideoModal {...defaultProps} />);
        expect(document.body.style.overflow).toBe('hidden');
        unmount();
        expect(document.body.style.overflow).toBe('');
    });
});
