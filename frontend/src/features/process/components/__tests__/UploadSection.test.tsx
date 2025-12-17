import React from 'react';
import { render, screen } from '@testing-library/react';
import { UploadSection } from '../UploadSection';
import { I18nProvider } from '@/context/I18nContext';
import { useProcessContext } from '../../ProcessContext';

// Mock useProcessContext
jest.mock('../../ProcessContext', () => ({
    useProcessContext: jest.fn(),
}));

const mockContextValue = {
    selectedFile: new File([''], 'test.mp4', { type: 'video/mp4' }),
    onFileSelect: jest.fn(),
    isProcessing: true,
    hasChosenModel: true,
    transcribeProvider: 'local',
    transcribeMode: 'fast',
    AVAILABLE_MODELS: [
        {
            id: 'standard',
            provider: 'local',
            mode: 'fast',
            name: 'Standard',
            icon: () => <span>Standard</span>,
            description: 'Standard model',
            badge: 'Standard',
            badgeColor: 'text-gray-500 bg-gray-100',
            stats: { speed: 100, accuracy: 90, karaoke: false, lines: 'auto' },
            colorClass: (selected: boolean) => selected ? 'selected-class' : 'unselected-class',
        }
    ],
    currentStep: 2,
    setOverrideStep: jest.fn(),
    setHasChosenModel: jest.fn(),
    onJobSelect: jest.fn(),
    onReset: jest.fn(),
    handleStart: jest.fn(),
    fileInputRef: { current: null },
    resultsRef: { current: null },
    videoInfo: null,
    setVideoInfo: jest.fn(),
    setPreviewVideoUrl: jest.fn(),
    setCues: jest.fn(),
    selectedJob: null,
    error: null,
    progress: 45,
    statusMessage: 'Transcribing...',
    onCancelProcessing: jest.fn(),
    videoUrl: null
};

// Mock URL.createObjectURL
if (typeof window.URL.createObjectURL === 'undefined') {
  Object.defineProperty(window.URL, 'createObjectURL', { value: jest.fn() });
}
if (typeof window.URL.revokeObjectURL === 'undefined') {
    Object.defineProperty(window.URL, 'revokeObjectURL', { value: jest.fn() });
}

// Mock HTMLMediaElement.prototype.load
Object.defineProperty(HTMLMediaElement.prototype, 'load', {
    configurable: true,
    value: jest.fn(),
});

describe('UploadSection', () => {
    beforeEach(() => {
        (useProcessContext as jest.Mock).mockReturnValue(mockContextValue);
    });

    it('renders progress bar with correct ARIA attributes when processing', () => {
        render(
            <I18nProvider initialLocale="en">
                <UploadSection />
            </I18nProvider>
        );

        const progressBar = screen.getByRole('progressbar');
        expect(progressBar).toBeInTheDocument();
        expect(progressBar).toHaveAttribute('aria-valuenow', '45');
        expect(progressBar).toHaveAttribute('aria-valuemin', '0');
        expect(progressBar).toHaveAttribute('aria-valuemax', '100');

        // Check label association
        expect(progressBar).toHaveAttribute('aria-labelledby', 'progress-label');
        const label = document.getElementById('progress-label');
        expect(label).toHaveTextContent('Transcribing...');
        expect(label).toHaveTextContent('45%');
    });
});
