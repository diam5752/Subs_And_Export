import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ProcessViewContent } from '../ProcessView';
import { I18nProvider } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { PlaybackProvider } from '../PlaybackContext';

// Global mock for HTMLMediaElement methods not implemented in JSDOM
beforeAll(() => {
    Object.defineProperty(window.HTMLMediaElement.prototype, 'load', {
        configurable: true,
        value: jest.fn(),
    });
});

const mockJob = {
    id: 'test-job-id',
    status: 'completed',
    progress: 100,
    created_at: 1234567890,
    updated_at: 1234567890,
    result_data: {
        original_filename: 'test_video.mp4',
        video_path: '/videos/test_video.mp4',
        duration: 10,
        width: 1080,
        height: 1920
    }
};

const mockContextValue = {
    currentStep: 1,
    progress: 0,
    isProcessing: false,
    selectedJob: null,
    activeSidebarTab: 'transcript',
    setActiveSidebarTab: jest.fn(),
    STYLE_PRESETS: [
        {
            id: 'tiktok',
            name: 'TikTok Pro',
            description: 'Viral, attention-grabbing',
            emoji: '🎵',
            colorClass: 'from-yellow-500 to-orange-500',
            settings: { position: 16, lines: 1, size: 100, color: '#FFFF00', karaoke: true }
        }
    ],
    activePreset: 'tiktok',
    setActivePreset: jest.fn(),
    cues: [],
    currentTime: 0,
    videoUrl: null,
    handleFileSelect: jest.fn(),
    handleSubmit: jest.fn(),
    onCancelProcessing: jest.fn(),
    processedCues: [],
    subtitlePosition: 16,
    setSubtitlePosition: jest.fn(),
    subtitleSize: 100,
    setSubtitleSize: jest.fn(),
    maxSubtitleLines: 1,
    setMaxSubtitleLines: jest.fn(),
    subtitleColor: '#FFFF00',
    setSubtitleColor: jest.fn(),
    karaokeEnabled: false,
    setKaraokeEnabled: jest.fn(),
    lastUsedSettings: null,
    SUBTITLE_COLORS: [],
    playerRef: { current: null },
    transcriptContainerRef: { current: null },
    editingCueIndex: null,
    editingCueSurface: null,
    editingCueDraft: '',
    handleUpdateDraft: jest.fn(),
    beginEditingCue: jest.fn(),
    saveEditingCue: jest.fn(),
    cancelEditingCue: jest.fn(),
    statusMessage: '',
    shadowStrength: 0,
    resultsRef: { current: null },
    setOverrideStep: jest.fn(),
    handleExport: jest.fn(),
    exportingResolutions: {},
    exportError: null,
    videoInfo: null,
    previewVideoUrl: null,
    onFileSelect: jest.fn(),
    onStartProcessing: jest.fn(),
    onReset: jest.fn(),
    onJobSelect: jest.fn(),
    statusStyles: {},
    buildStaticUrl: jest.fn(),
    setVideoInfo: jest.fn(),
    setPreviewVideoUrl: jest.fn(),
    setCues: jest.fn(),
    setCurrentTime: jest.fn(),
    fileInputRef: { current: null },
    handleStart: jest.fn(),
    saveLastUsedSettings: jest.fn(),
    setEditingCueIndex: jest.fn(),
    setEditingCueDraft: jest.fn(),
    isSavingTranscript: false,
    transcriptSaveError: null,
    setTranscriptSaveError: jest.fn(),
    updateCueText: jest.fn(),
};

// Mock useProcessContext
jest.mock('../ProcessContext', () => ({
    useProcessContext: jest.fn(),
}));

// Mock browser APIs
window.HTMLElement.prototype.scrollIntoView = jest.fn();
window.HTMLElement.prototype.scrollTo = jest.fn();
window.URL.createObjectURL = jest.fn();
window.URL.revokeObjectURL = jest.fn();

describe('ProcessView', () => {
    beforeEach(() => {
        (useProcessContext as jest.Mock).mockReturnValue(mockContextValue);
    });

    it('renders Step 1 initially', () => {
        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );
        expect(screen.getAllByText(/Step 1/i).length).toBeGreaterThan(0);
        expect(screen.getByRole('button', { name: /choose video/i })).toBeInTheDocument();
        expect(screen.queryByTestId('mock-mode-badge')).not.toBeInTheDocument();
        expect(screen.queryByTestId('engine-settings-toggle')).not.toBeInTheDocument();
    });

    it('renders Step 2 (Captions) when a file is selected', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 2,
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.getAllByText(/Step 2/i).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/^Captions$/i).length).toBeGreaterThan(0);
    });

    it('renders Step 3 (Preview) when job is completed', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 3,
            selectedJob: { ...mockJob, status: 'completed' },
            cues: [{ start: 0, end: 1, text: 'Test' }]
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.getAllByText(/Step 3/i).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/^Export$/i).length).toBeGreaterThan(0);
        expect(screen.getByRole('tab', { name: /Transcript/i })).toBeInTheDocument();

        const stepper = screen.getByTestId('workflow-stepper');
        const editor = screen.getByTestId('completed-editor');
        expect(screen.getAllByText(/Step 3/i)).toHaveLength(1);
        expect(stepper.compareDocumentPosition(editor) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('switches between Transcript and Styles tabs', async () => {
        const setActiveSidebarTab = jest.fn();
        let activeTab = 'transcript';

        (useProcessContext as jest.Mock).mockImplementation(() => ({
            ...mockContextValue,
            currentStep: 3,
            selectedJob: { ...mockJob, status: 'completed' },
            activeSidebarTab: activeTab,
            setActiveSidebarTab: (val: string) => {
                activeTab = val;
                setActiveSidebarTab(val);
            }
        }));

        const { rerender } = render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );

        const stylesTab = screen.getByText('Styles');
        fireEvent.click(stylesTab);

        expect(setActiveSidebarTab).toHaveBeenCalledWith('styles');

        // Update mock for re-render
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 3,
            selectedJob: { ...mockJob, status: 'completed' },
            activeSidebarTab: 'styles',
            setActiveSidebarTab
        });

        rerender(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );

        await waitFor(() => {
            expect(screen.getAllByText(/TikTok Pro/i).length).toBeGreaterThan(0);
        });
    });

    it('renders accessible progress bar during processing', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 2,
            isProcessing: true,
            progress: 45,
            statusMessage: 'Processing...',
            selectedFile: new File([''], 'video.mp4', { type: 'video/mp4' }),
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );

        const progressBar = screen.getByRole('progressbar', { name: /Processing.../i });
        expect(progressBar).toBeInTheDocument();
        expect(progressBar).toHaveAttribute('aria-valuenow', '45');
        expect(progressBar).toHaveAttribute('aria-valuemin', '0');
        expect(progressBar).toHaveAttribute('aria-valuemax', '100');
    });

    it('keeps internal engine details out of the product workspace', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 2,
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.queryByTestId('mock-mode-badge')).not.toBeInTheDocument();
        expect(screen.queryByTestId('engine-settings-toggle')).not.toBeInTheDocument();
        expect(screen.queryByText('Mock Studio')).not.toBeInTheDocument();
        expect(screen.queryByText('€0')).not.toBeInTheDocument();
    });

    it('keeps the completed editor focused without duplicating the upload card', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 3, // Step 3 active, Step 2 collapsed
            selectedFile: new File([''], 'test.mp4', { type: 'video/mp4' }),
            selectedJob: mockJob,
            cues: [{ start: 0, end: 1, text: 'Test' }],
            videoInfo: { thumbnailUrl: 'http://example.com/thumb.jpg' }
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.queryByTestId('upload-section')).not.toBeInTheDocument();
        expect(screen.getByRole('tab', { name: /Transcript/i })).toBeInTheDocument();
    });

    it('restores a completed job directly into the export editor', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 3,
            selectedFile: null, // Critical for refresh case
            selectedJob: mockJob, // completed job
            videoInfo: { thumbnailUrl: 'http://example.com/thumb.jpg' }
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <ProcessViewContent />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.queryByTestId('upload-section')).not.toBeInTheDocument();
        expect(screen.getByRole('tab', { name: /Transcript/i })).toBeInTheDocument();
        expect(screen.getByTestId('workflow-stepper')).toHaveTextContent('Export');
    });

    it('navigates and scrolls to an unlocked workflow step', () => {
        jest.useFakeTimers();
        const setOverrideStep = jest.fn();
        const scrollTo = jest.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 3,
            selectedJob: mockJob,
            setOverrideStep,
        });

        try {
            render(
                <I18nProvider initialLocale="en">
                    <PlaybackProvider>
                        <ProcessViewContent />
                    </PlaybackProvider>
                </I18nProvider>,
            );

            fireEvent.click(screen.getByRole('button', { name: /Step 3 Export/i }));
            jest.advanceTimersByTime(180);

            expect(setOverrideStep).toHaveBeenCalledWith(3);
            expect(scrollTo).toHaveBeenCalledWith({ top: -108, behavior: 'smooth' });
        } finally {
            scrollTo.mockRestore();
            jest.useRealTimers();
        }
    });
});
