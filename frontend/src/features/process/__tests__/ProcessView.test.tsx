import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ProcessViewContent } from '../ProcessView';
import { I18nProvider } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';

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
    transcribeProvider: 'groq',
    transcribeMode: 'standard',
    AVAILABLE_MODELS: [
        {
            id: 'standard',
            provider: 'groq',
            mode: 'standard',
            name: 'Standard',
            icon: () => <span>Standard</span>,
            description: 'Standard model',
            badge: 'Standard',
            badgeColor: 'text-gray-500 bg-gray-100',
            stats: { speed: 100, accuracy: 90, karaoke: false, lines: 'auto' },
            colorClass: (selected: boolean) => selected ? 'selected-class' : 'unselected-class',
        }
    ],
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
    setTranscribeProvider: jest.fn(),
    setTranscribeMode: jest.fn(),
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
    videoInfo: null,
    previewVideoUrl: null,
    onFileSelect: jest.fn(),
    onStartProcessing: jest.fn(),
    onReset: jest.fn(),
    onJobSelect: jest.fn(),
    statusStyles: {},
    buildStaticUrl: jest.fn(),
    hasChosenModel: false,
    setHasChosenModel: jest.fn(),
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
                <ProcessViewContent />
            </I18nProvider>
        );
        expect(screen.getAllByText(/Step 1/i).length).toBeGreaterThan(0);
        expect(screen.getByRole('heading', { name: /select a model/i })).toBeInTheDocument();
        expect(screen.getByText(/choose the engine before uploading/i)).toBeInTheDocument();
    });

    it('allows selecting a model', () => {
        const setTranscribeProvider = jest.fn();
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            setTranscribeProvider
        });

        render(
            <I18nProvider initialLocale="en">
                <ProcessViewContent />
            </I18nProvider>
        );

        const radio = screen.getByRole('radio', { name: /Standard/i });
        fireEvent.click(radio);

        expect(setTranscribeProvider).toHaveBeenCalledWith('groq');
    });

    it('renders Step 2 (Upload) when file is selected', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 2,
            transcribeProvider: 'groq'
        });

        render(
            <I18nProvider initialLocale="en">
                <ProcessViewContent />
            </I18nProvider>
        );

        expect(screen.getAllByText(/Step 2/i).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/^Upload$/i).length).toBeGreaterThan(0);
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
                <ProcessViewContent />
            </I18nProvider>
        );

        expect(screen.getAllByText(/Step 3/i).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/^Preview$/i).length).toBeGreaterThan(0);
        expect(screen.getByRole('tab', { name: /Transcript/i })).toBeInTheDocument();
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
                <ProcessViewContent />
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
                <ProcessViewContent />
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
            hasChosenModel: true
        });

        render(
            <I18nProvider initialLocale="en">
                <ProcessViewContent />
            </I18nProvider>
        );

        const progressBar = screen.getByRole('progressbar', { name: /Processing.../i });
        expect(progressBar).toBeInTheDocument();
        expect(progressBar).toHaveAttribute('aria-valuenow', '45');
        expect(progressBar).toHaveAttribute('aria-valuemin', '0');
        expect(progressBar).toHaveAttribute('aria-valuemax', '100');
    });

    it('shows chevron arrow in both Step 1 and Step 2 headers', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 2,
            hasChosenModel: true
        });

        render(
            <I18nProvider initialLocale="en">
                <ProcessViewContent />
            </I18nProvider>
        );

        // Verify Step 1 chevron
        expect(screen.getByTestId('step-1-chevron')).toBeInTheDocument();
        // Verify Step 2 chevron
        expect(screen.getByTestId('step-2-chevron')).toBeInTheDocument();
    });

    it('displays thumbnail preview in collapsed Step 2 header', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 3, // Step 3 active, Step 2 collapsed
            hasChosenModel: true,
            selectedFile: new File([''], 'test.mp4', { type: 'video/mp4' }),
            videoInfo: { thumbnailUrl: 'http://example.com/thumb.jpg' }
        });

        render(
            <I18nProvider initialLocale="en">
                <ProcessViewContent />
            </I18nProvider>
        );

        // In Step 3, Step 2 is collapsed. It should show the thumbnail image.
        // We use getAllByAltText because it might appear in both compact and full view (even if one is hidden)
        const thumbnails = screen.getAllByAltText('Thumbnail');
        expect(thumbnails.length).toBeGreaterThanOrEqual(1);
        expect(thumbnails[0]).toHaveAttribute('src', expect.stringContaining('http://example.com/thumb.jpg'));
    });

    it('renders Step 2 in compact mode on page refresh (selectedFile is null, job is active)', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            currentStep: 3,
            hasChosenModel: true,
            selectedFile: null, // Critical for refresh case
            selectedJob: mockJob, // completed job
            videoInfo: { thumbnailUrl: 'http://example.com/thumb.jpg' }
        });

        const { container } = render(
            <I18nProvider initialLocale="en">
                <ProcessViewContent />
            </I18nProvider>
        );

        // Verify the compact section is present
        const compactSection = container.querySelector('#upload-section-compact');
        expect(compactSection).toBeInTheDocument();

        // Should also show "Ready" badge
        expect(screen.getByText(/Ready/i)).toBeInTheDocument();
    });
});
