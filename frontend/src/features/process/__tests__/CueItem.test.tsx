import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { CueItem } from '../CueItem';

// Mock useI18n
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({
        t: (key: string) => key,
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
        draftText: '',
        isSaving: false,
        onSeek: jest.fn(),
        onEdit: jest.fn(),
        onSave: jest.fn(),
        onCancel: jest.fn(),
        onUpdateDraft: jest.fn(),
    };

    it('renders correctly in view mode', () => {
        render(<CueItem {...defaultProps} />);
        expect(screen.getByText('Hello World')).toBeInTheDocument();
        expect(screen.getByText('transcriptEdit')).toBeInTheDocument();
    });

    it('renders correctly in edit mode', () => {
        render(<CueItem {...defaultProps} isEditing={true} draftText="Editing..." />);
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

    it('calls onUpdateDraft when typing', () => {
        render(<CueItem {...defaultProps} isEditing={true} />);
        const textarea = screen.getByRole('textbox');
        fireEvent.change(textarea, { target: { value: 'New' } });
        expect(defaultProps.onUpdateDraft).toHaveBeenCalledWith('New');
    });
});
