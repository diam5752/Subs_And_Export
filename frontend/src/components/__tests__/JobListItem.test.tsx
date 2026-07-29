import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { JobListItem } from '../JobListItem';
import { JobResponse } from '@/lib/api';

const mockJob: JobResponse = {
    id: 'job-123',
    status: 'completed',
    progress: 100,
    message: null,
    created_at: 1625000000,
    updated_at: 1625000000,
    expires_at: 1625086400,
    result_data: {
        video_path: '/path/to/video.mp4',
        artifacts_dir: '/artifacts',
        original_filename: 'test-video.mp4',
        public_url: 'http://example.com/video.mp4'
    }
};

describe('JobListItem', () => {
    const mockProps = {
        job: mockJob,
        selectionMode: false,
        isSelected: false,
        isExpired: false,
        publicUrl: 'http://example.com/video.mp4',
        timestamp: 1625000000000,
        formatDate: () => '2021-06-29',
        onToggleSelection: jest.fn(),
        onJobSelect: jest.fn(),
        setShowPreview: jest.fn(),
        isConfirmingDelete: false,
        isDeleting: false,
        setConfirmDeleteId: jest.fn(),
        onDeleteConfirmed: jest.fn(),
        t: (key: string) => key,
    };

    beforeEach(() => {
        Object.defineProperty(window, 'requestAnimationFrame', {
            writable: true,
            value: (callback: FrameRequestCallback) => {
                callback(0);
                return 1;
            },
        });
    });

    it('renders job details correctly', () => {
        render(<JobListItem {...mockProps} />);
        expect(screen.getByText('test-video.mp4')).toBeInTheDocument();
        expect(screen.getByText('2021-06-29')).toBeInTheDocument();
    });

    it('shows how long the temporary project remains available', () => {
        jest.useFakeTimers().setSystemTime(new Date('2021-06-30T00:00:00Z'));
        const expiresAt = Math.floor(Date.now() / 1000) + (3 * 3600);

        render(
            <JobListItem
                {...mockProps}
                job={{ ...mockJob, expires_at: expiresAt }}
                t={(key, params) => key === 'availableForHours'
                    ? `available ${params?.hours}h`
                    : key}
            />,
        );

        // REGRESSION: history previously hid an upload-only 24-hour cleanup
        // rule and gave no deadline for generated exports.
        expect(screen.getByText('available 3h')).toBeInTheDocument();
        jest.useRealTimers();
    });

    it('shows download and view buttons with accessible labels when completed', () => {
        const { container } = render(<JobListItem {...mockProps} />);
        const download = screen.getByLabelText('download test-video.mp4');
        expect(download).toHaveAttribute('download', 'test-video_subs.mp4');
        expect(download).toHaveAttribute(
            'href',
            'http://example.com/video.mp4?download=true&filename=test-video_subs.mp4',
        );
        expect(download).toHaveClass('min-h-11');
        expect(screen.getByLabelText('view test-video.mp4')).toHaveClass('min-h-11');
        expect(screen.getByLabelText('deleteJob test-video.mp4')).toHaveClass(
            'h-11',
            'min-w-11',
        );
        expect(container.querySelector('.recent-job-actions')).toHaveClass(
            'w-full',
            'sm:w-auto',
        );
    });

    it('handles selection toggle in selection mode', () => {
        render(<JobListItem {...mockProps} selectionMode={true} />);
        fireEvent.click(screen.getByText('test-video.mp4').closest('div')!.parentElement!);
        expect(mockProps.onToggleSelection).toHaveBeenCalledWith('job-123', false);
    });

    it('shows delete confirmation with accessible label', () => {
        render(<JobListItem {...mockProps} isConfirmingDelete={true} />);
        expect(screen.getByLabelText('confirmDelete test-video.mp4')).toHaveClass(
            'h-11',
            'min-w-11',
        );
        expect(screen.getByLabelText('cancel')).toHaveClass('h-11', 'min-w-11');
    });

    it('shows loading state with accessible label', () => {
        render(<JobListItem {...mockProps} isConfirmingDelete={true} isDeleting={true} />);
        expect(screen.getByLabelText('deleting test-video.mp4')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'deleting test-video.mp4' })).toHaveAttribute('aria-busy', 'true');
    });

    it('opens the preview when clicking view and forwards the selected job', () => {
        render(<JobListItem {...mockProps} />);

        fireEvent.click(screen.getByLabelText('view test-video.mp4'));

        expect(mockProps.onJobSelect).toHaveBeenCalledWith(mockJob);
        expect(mockProps.setShowPreview).toHaveBeenCalledWith(true);
    });

    it('opens the delete confirmation and confirms deletion', () => {
        const { rerender } = render(<JobListItem {...mockProps} />);

        fireEvent.click(screen.getByLabelText('deleteJob test-video.mp4'));
        expect(mockProps.setConfirmDeleteId).toHaveBeenCalledWith('job-123');

        rerender(<JobListItem {...mockProps} isConfirmingDelete={true} />);
        fireEvent.click(screen.getByLabelText('confirmDelete test-video.mp4'));

        expect(mockProps.onDeleteConfirmed).toHaveBeenCalledWith('job-123');
    });

    it('restores focus to the delete button after cancelling confirmation', () => {
        const { rerender } = render(<JobListItem {...mockProps} />);
        const focusSpy = jest.spyOn(HTMLButtonElement.prototype, 'focus').mockImplementation(() => { });

        rerender(<JobListItem {...mockProps} isConfirmingDelete={true} />);
        rerender(<JobListItem {...mockProps} isConfirmingDelete={true} />);
        fireEvent.click(screen.getByLabelText('cancel'));
        rerender(<JobListItem {...mockProps} isConfirmingDelete={false} />);

        expect(focusSpy).toHaveBeenCalled();
        expect(mockProps.setConfirmDeleteId).toHaveBeenCalledWith(null);
    });

    it('shows the expired badge instead of actions for expired jobs', () => {
        render(<JobListItem {...mockProps} isExpired={true} publicUrl={null} />);

        expect(screen.getByText('expired')).toBeInTheDocument();
        expect(screen.queryByLabelText('view test-video.mp4')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('download test-video.mp4')).not.toBeInTheDocument();
    });

    it('has correct accessibility attributes', () => {
        const { rerender } = render(<JobListItem {...mockProps} selectionMode={true} />);

        // Container role
        // In selection mode, the container should be a button.
        const container = screen.getByRole('button');
        expect(container).toBeInTheDocument();
        expect(container).toHaveAttribute('tabIndex', '0');

        // Checkbox should be hidden from AT
        expect(screen.queryByLabelText('selectMode')).not.toBeInTheDocument();

        // Test keyboard interaction
        fireEvent.keyDown(container, { key: 'Enter', code: 'Enter' });
        expect(mockProps.onToggleSelection).toHaveBeenCalledWith('job-123', false);

        rerender(<JobListItem {...mockProps} selectionMode={false} />);

        // Delete button label
        expect(screen.getByLabelText('deleteJob test-video.mp4')).toBeInTheDocument();
    });
});
