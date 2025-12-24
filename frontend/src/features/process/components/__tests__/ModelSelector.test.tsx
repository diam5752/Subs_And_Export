import React from 'react';
import { render, screen } from '@testing-library/react';
import { ModelSelector } from '../ModelSelector';
import { TranscribeProvider, TranscribeMode } from '../../ProcessContext';

// Mock context values
const mockContext = {
    AVAILABLE_MODELS: [
        {
            id: 'groq-standard',
            provider: 'groq',
            mode: 'standard',
            name: 'Groq Standard',
            icon: () => <span>Icon</span>,
            stats: { speed: 5, quality: 3, karaoke: false }
        }
    ],
    transcribeProvider: 'groq' as TranscribeProvider,
    transcribeMode: 'standard' as TranscribeMode,
    setTranscribeProvider: jest.fn(),
    setTranscribeMode: jest.fn(),
    setHasChosenModel: jest.fn(),
    setOverrideStep: jest.fn(),
    hasChosenModel: false,
    currentStep: 1,
    selectedJob: null,
};

// Mock I18n
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key })
}));

// Mock useProcessContext directly since ProcessContext is not exported
jest.mock('../../ProcessContext', () => {
    const originalModule = jest.requireActual('../../ProcessContext');
    return {
        ...originalModule,
        useProcessContext: () => mockContext,
    };
});

describe('ModelSelector', () => {
    it('renders the info tooltip as a button', () => {
        render(<ModelSelector />);

        // Check for the tooltip button
        const tooltipButton = screen.getByLabelText('modelInfo');
        expect(tooltipButton.tagName).toBe('BUTTON');
        expect(tooltipButton).toHaveAttribute('type', 'button');
        // Ensure it has the correct classes for visibility
        expect(tooltipButton).toHaveClass('group/info');
    });
});
