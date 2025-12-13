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
        confirmDeleteId: null,
        setConfirmDeleteId: jest.fn(),
        deletingJobId: null,
        setDeletingJobId: jest.fn(),
        onRefreshJobs: jest.fn(),
        selectedJobId: undefined,
        t: (key: string) => key,
    };

    it('renders job details correctly', () => {
        render(<JobListItem {...mockProps} />);
        expect(screen.getByText('test-video.mp4')).toBeInTheDocument();
        expect(screen.getByText('2021-06-29')).toBeInTheDocument();
    });

    it('shows download and view buttons when completed and not selection mode', () => {
        render(<JobListItem {...mockProps} />);
        expect(screen.getByText('download')).toBeInTheDocument();
        expect(screen.getByText('view')).toBeInTheDocument();
    });

    it('handles selection toggle in selection mode', () => {
        render(<JobListItem {...mockProps} selectionMode={true} />);
        fireEvent.click(screen.getByText('test-video.mp4').closest('div')!.parentElement!);
        expect(mockProps.onToggleSelection).toHaveBeenCalledWith('job-123', false);
    });

    it('shows delete confirmation when confirmDeleteId matches', () => {
        render(<JobListItem {...mockProps} confirmDeleteId="job-123" />);
        expect(screen.getByText('✓')).toBeInTheDocument();
        expect(screen.getByText('✕')).toBeInTheDocument();
    });

    it('has correct accessibility attributes', () => {
        const { rerender } = render(<JobListItem {...mockProps} selectionMode={true} />);

        // Container role
        // In selection mode, the container should be a button.
        // There are no other buttons visible in selection mode.
        const container = screen.getByRole('button');
        expect(container).toBeInTheDocument();
        expect(container).toHaveAttribute('tabIndex', '0');

        // Checkbox should be hidden from AT or at least not the primary interaction
        // Since we put aria-hidden=true, it shouldn't be accessible by label
        expect(screen.queryByLabelText('selectMode')).not.toBeInTheDocument();

        // Test keyboard interaction
        fireEvent.keyDown(container, { key: 'Enter', code: 'Enter' });
        expect(mockProps.onToggleSelection).toHaveBeenCalledWith('job-123', false);

        fireEvent.keyDown(container, { key: ' ', code: 'Space' });
        expect(mockProps.onToggleSelection).toHaveBeenCalledWith('job-123', false);

        rerender(<JobListItem {...mockProps} selectionMode={false} />);

        // Delete button label
        expect(screen.getByLabelText('deleteJob')).toBeInTheDocument();

        // Confirm delete mode
        rerender(<JobListItem {...mockProps} confirmDeleteId="job-123" />);
        expect(screen.getByLabelText('confirmDelete')).toBeInTheDocument();
        expect(screen.getByLabelText('cancel')).toBeInTheDocument();
    });
});
