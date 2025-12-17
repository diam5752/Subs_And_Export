import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { ProcessView } from '../ProcessView';
import { JobResponse } from '@/lib/api';
import { I18nProvider } from '@/context/I18nContext';
import { AppEnvProvider } from '@/context/AppEnvContext';
import en from '@/i18n/en.json';

// Mock dependencies
jest.mock('@/lib/api', () => ({
    api: {
        updateJobTranscription: jest.fn().mockResolvedValue({ status: 'ok' }),
        exportVideo: jest.fn().mockResolvedValue({ id: 'job-123', status: 'pending' }),
        loadDevSampleJob: jest.fn().mockResolvedValue({ id: 'sample-job', status: 'completed' }),
    },
    API_BASE: 'http://localhost:8000',
}));

jest.mock('@/lib/video', () => ({
    validateVideoAspectRatio: jest.fn().mockResolvedValue({
        width: 1080,
        height: 1920,
        aspectWarning: false,
        thumbnailUrl: 'blob:thumb',
    }),
}));

// Mock URL.createObjectURL
global.URL.createObjectURL = jest.fn(() => 'blob:test');
global.URL.revokeObjectURL = jest.fn();

// Mock scrollIntoView
Element.prototype.scrollIntoView = jest.fn();
window.scrollTo = jest.fn();

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
    observe() { }
    unobserve() { }
    disconnect() { }
};

// Mock fetch
global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
    })
) as jest.Mock;

const mockJob: JobResponse = {
    id: 'job-123',
    status: 'completed',
    progress: 100,
    message: null,
    created_at: 1234567890,
    updated_at: 1234567890,
    result_data: {
        video_path: '/videos/output.mp4',
        artifacts_dir: '/videos',
        public_url: '/videos/output.mp4',
        original_filename: 'test-video.mp4',
        transcription_url: '/transcription.json',
    },
};

const defaultProps = {
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
    buildStaticUrl: (path?: string | null) => path || null,
};

const renderWithProviders = (ui: React.ReactNode) => {
    return render(
        <AppEnvProvider appEnv="dev">
            <I18nProvider initialLocale="en">
                {ui}
            </I18nProvider>
        </AppEnvProvider>
    );
};

describe('ProcessView', () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('renders Step 1 initially', () => {
        renderWithProviders(<ProcessView {...defaultProps} />);

        expect(screen.getByRole('radiogroup', { name: en.modelSelectTitle })).toBeInTheDocument();
        // Check for model options - Use regex to match potential whitespace or substrings
        expect(screen.getByText(/Standard/)).toBeInTheDocument();
        expect(screen.getByText(/Enhanced/)).toBeInTheDocument();
        expect(screen.getByText(/Ultimate/)).toBeInTheDocument();
    });

    it('allows selecting a model', async () => {
        renderWithProviders(<ProcessView {...defaultProps} />);

        // Find by role which is better for accessibility and avoid testId issues if not present on wrapper
        const enhancedModel = screen.getByRole('radio', { name: /Enhanced/i });
        fireEvent.click(enhancedModel);

        // Should advance to step 2 (Upload)
        await screen.findByText(new RegExp(en.statusSynced, 'i'));

        const uploadSection = document.getElementById('upload-section');
        expect(uploadSection).not.toBeNull();
        expect(uploadSection).not.toHaveClass('opacity-40');
    });

    it('renders Step 2 (Upload) when file is selected', async () => {
        const props = { ...defaultProps, selectedFile: new File([''], 'test.mp4', { type: 'video/mp4' }) };

        await act(async () => {
            renderWithProviders(<ProcessView {...props} />);
        });

        // Use waitFor to ensure state updates propagate
        await waitFor(() => {
            // Should show compact upload view
            expect(screen.getByText('Upload Video')).toBeInTheDocument();
            // Check for the filename which should be present in compact view
            expect(screen.getAllByText('test.mp4').length).toBeGreaterThan(0);
        });
    });

    it('renders Step 3 (Preview) when job is completed', async () => {
        const props = { ...defaultProps, selectedJob: mockJob };

        await act(async () => {
            renderWithProviders(<ProcessView {...props} />);
        });

        expect(screen.getByText('Preview & Export')).toBeInTheDocument();
        // Use getAllByText for filename as it might appear multiple times (status header + preview)
        expect(screen.getAllByText('test-video.mp4').length).toBeGreaterThan(0);

        // Sidebar tabs
        expect(screen.getByText('Transcript')).toBeInTheDocument();
        expect(screen.getByText('Styles')).toBeInTheDocument();
    });

    it('switches between Transcript and Styles tabs', async () => {
        const props = { ...defaultProps, selectedJob: mockJob };

        await act(async () => {
            renderWithProviders(<ProcessView {...props} />);
        });

        const stylesTab = screen.getByText('Styles');
        fireEvent.click(stylesTab);

        // Should show style presets
        // Use queryAllByText to handle potential multiple elements or fuzzy match
        expect(screen.getAllByText(/TikTok Pro/i).length).toBeGreaterThan(0);

        const transcriptTab = screen.getByText('Transcript');
        fireEvent.click(transcriptTab);
    });

    it('has accessible ARIA tab interface for sidebar', async () => {
        const props = { ...defaultProps, selectedJob: mockJob };

        await act(async () => {
            renderWithProviders(<ProcessView {...props} />);
        });

        // Check tablist
        const tablist = screen.getByRole('tablist', { name: /Sidebar tabs/i });
        expect(tablist).toBeInTheDocument();

        // Check tabs
        const transcriptTab = screen.getByRole('tab', { name: 'Transcript' });
        const stylesTab = screen.getByRole('tab', { name: 'Styles' });

        expect(transcriptTab).toHaveAttribute('aria-selected', 'true');
        expect(stylesTab).toHaveAttribute('aria-selected', 'false');

        // Check panel
        const panel = screen.getByRole('tabpanel');
        expect(panel).toHaveAttribute('aria-labelledby', 'tab-transcript');
        expect(panel).toHaveAttribute('tabIndex', '0');

        // Switch tab
        fireEvent.click(stylesTab);

        expect(transcriptTab).toHaveAttribute('aria-selected', 'false');
        expect(stylesTab).toHaveAttribute('aria-selected', 'true');

        const stylePanel = screen.getByRole('tabpanel');
        expect(stylePanel).toHaveAttribute('aria-labelledby', 'tab-styles');
    });
});
