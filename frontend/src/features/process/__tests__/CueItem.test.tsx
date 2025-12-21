import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { CueItem } from '../CueItem';

// Mock useI18n
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({
        t: (key: string) => {
            if (key === 'jumpToTime') return 'Jump to {time}';
            if (key === 'jumpToCue') return 'Jump to cue: {text}';
            return key;
        },
    }),
}));

const mockCue = {
    start: 0,
    end: 2,
    text: 'Hello World',
};

describe('CueItem', () => {
    const defaultProps = {
        cue: mockCue,
        index: 0,
        isActive: false,
        isEditing: false,
        canEdit: true,
        initialDraftText: '',
        isSaving: false,
        onSeek: jest.fn(),
        onEdit: jest.fn(),
        onSave: jest.fn(),
        onCancel: jest.fn(),
    };

    it('renders correctly in view mode with accessible labels', () => {
        render(<CueItem {...defaultProps} />);
        expect(screen.getByText('Hello World')).toBeInTheDocument();
        expect(screen.getByText('transcriptEdit')).toBeInTheDocument();

        // Check ARIA labels
        expect(screen.getByLabelText('Jump to 0:00')).toBeInTheDocument();
        expect(screen.getByLabelText('Jump to cue: Hello World')).toBeInTheDocument();
    });

    it('renders correctly in edit mode', () => {
        render(<CueItem {...defaultProps} isEditing={true} initialDraftText="Editing..." />);
        expect(screen.getByDisplayValue('Editing...')).toBeInTheDocument();
        expect(screen.getByText('transcriptSave')).toBeInTheDocument();
        expect(screen.getByText('transcriptCancel')).toBeInTheDocument();
    });

    it('calls onSeek when clicked', () => {
        render(<CueItem {...defaultProps} />);
        fireEvent.click(screen.getByText('0:00'));
        expect(defaultProps.onSeek).toHaveBeenCalledWith(0);
    });

    it('calls onEdit when edit button clicked', () => {
        render(<CueItem {...defaultProps} />);
        fireEvent.click(screen.getByText('transcriptEdit'));
        expect(defaultProps.onEdit).toHaveBeenCalledWith(0);
    });

    it('updates local state and calls onSave with new text', () => {
        render(<CueItem {...defaultProps} isEditing={true} initialDraftText="Initial" />);
        const textarea = screen.getByRole('textbox');

        // Typing should update local state but not trigger external callbacks yet
        fireEvent.change(textarea, { target: { value: 'New Text' } });
        expect(textarea).toHaveValue('New Text');

        // Save should pass the local text
        fireEvent.click(screen.getByText('transcriptSave'));
        expect(defaultProps.onSave).toHaveBeenCalledWith('New Text');
    });
});
