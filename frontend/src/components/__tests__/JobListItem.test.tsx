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
        isConfirmingDelete: false,
        isDeleting: false,
        setConfirmDeleteId: jest.fn(),
        onDeleteConfirmed: jest.fn(),
        t: (key: string) => key,
    };

    it('renders job details correctly', () => {
        render(<JobListItem {...mockProps} />);
        expect(screen.getByText('test-video.mp4')).toBeInTheDocument();
        expect(screen.getByText('2021-06-29')).toBeInTheDocument();
    });

    it('shows download and view buttons with accessible labels when completed', () => {
        render(<JobListItem {...mockProps} />);
        expect(screen.getByLabelText('download test-video.mp4')).toBeInTheDocument();
        expect(screen.getByLabelText('view test-video.mp4')).toBeInTheDocument();
    });

    it('handles selection toggle in selection mode', () => {
        render(<JobListItem {...mockProps} selectionMode={true} />);
        fireEvent.click(screen.getByText('test-video.mp4').closest('div')!.parentElement!);
        expect(mockProps.onToggleSelection).toHaveBeenCalledWith('job-123', false);
    });

    it('shows delete confirmation with accessible label', () => {
        render(<JobListItem {...mockProps} isConfirmingDelete={true} />);
        expect(screen.getByLabelText('confirmDelete test-video.mp4')).toBeInTheDocument();
        expect(screen.getByLabelText('cancel')).toBeInTheDocument();
    });

    it('shows loading state with accessible label', () => {
        render(<JobListItem {...mockProps} isConfirmingDelete={true} isDeleting={true} />);
        expect(screen.getByLabelText('deleting test-video.mp4')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'deleting test-video.mp4' })).toHaveAttribute('aria-busy', 'true');
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
