import { render, screen, act } from '@testing-library/react';
import { ProcessView } from '../ProcessView';
import { JobResponse } from '@/lib/api';

// Mock the API client
jest.mock('@/lib/api', () => ({
    api: {
        updateJobTranscription: jest.fn(),
        exportVideo: jest.fn(),
        loadDevSampleJob: jest.fn(),
    },
    API_BASE: 'http://localhost:8000',
}));

// Mock the context providers
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('@/context/AppEnvContext', () => ({
    useAppEnv: () => ({ appEnv: 'prod' }),
}));

// Mock child components that might cause issues or aren't needed for this test
jest.mock('../PreviewPlayer', () => ({
    PreviewPlayer: () => <div data-testid="preview-player">Preview Player</div>,
}));

jest.mock('../VideoModal', () => ({
    VideoModal: () => <div data-testid="video-modal">Video Modal</div>,
}));

// Mock URL.createObjectURL
global.URL.createObjectURL = jest.fn(() => 'blob:test');
global.URL.revokeObjectURL = jest.fn();

// Mock scrollIntoView
window.HTMLElement.prototype.scrollIntoView = jest.fn();

// Mock video.load
HTMLMediaElement.prototype.load = jest.fn();

describe('ProcessView Accessibility', () => {
    const mockProps = {
        selectedFile: null,
        onFileSelect: jest.fn(),
        isProcessing: false,
        progress: 0,
        statusMessage: '',
        error: '',
        onStartProcessing: jest.fn(),
        onReset: jest.fn(),
        onCancelProcessing: jest.fn(),
        selectedJob: null,
        onJobSelect: jest.fn(),
        statusStyles: {},
        buildStaticUrl: jest.fn(),
    };

    it('renders model selection as a radiogroup with radio buttons', async () => {
        await act(async () => {
             render(<ProcessView {...mockProps} />);
        });

        // Check for radiogroup role
        const radioGroup = screen.getByRole('radiogroup');
        expect(radioGroup).toBeInTheDocument();

        // It should have an accessible label (either aria-label or via aria-labelledby)
        // In our implementation we used aria-label="modelSelectTitle" (since t returns key in mock)
        expect(radioGroup).toHaveAttribute('aria-label', 'modelSelectTitle');

        // Check for radio buttons
        const radioButtons = screen.getAllByRole('radio');
        expect(radioButtons.length).toBeGreaterThan(0); // Should be 3 models

        // Verify radio attributes
        radioButtons.forEach(button => {
            expect(button).toHaveAttribute('aria-checked');
        });
    });

    it('correctly marks the selected model as checked', async () => {
        // Render with a file selected so it defaults to a model (usually local/turbo)
        const file = new File([''], 'test.mp4', { type: 'video/mp4' });

        await act(async () => {
            render(<ProcessView {...mockProps} selectedFile={file} />);
        });

        const radioButtons = screen.getAllByRole('radio');

        // At least one should be checked (default selection logic)
        const checkedButtons = radioButtons.filter(b => b.getAttribute('aria-checked') === 'true');
        expect(checkedButtons.length).toBe(1);
    });
});
