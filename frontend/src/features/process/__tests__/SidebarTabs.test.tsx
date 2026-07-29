import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { Sidebar } from '../components/Sidebar';
import { I18nProvider } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';
import { PlaybackProvider } from '../PlaybackContext';

// Mock useProcessContext
jest.mock('../ProcessContext', () => ({
    useProcessContext: jest.fn(),
}));

// Mock ViralIntelligence to avoid deep rendering issues in this test
jest.mock('@/components/ViralIntelligence', () => ({
    ViralIntelligence: () => <div data-testid="viral-intelligence">Viral Intelligence Component</div>,
}));

const mockContextValue = {
    selectedJob: { id: 'test-job' },
    isProcessing: false,
    progress: 0,
    activeSidebarTab: 'transcript',
    setActiveSidebarTab: jest.fn(),
    cues: [],
    currentTime: 0,
    editingCueIndex: null,
    editingCueSurface: null,
    editingCueDraft: '',
    handleUpdateDraft: jest.fn(),
    beginEditingCue: jest.fn(),
    saveEditingCue: jest.fn(),
    cancelEditingCue: jest.fn(),
    playerRef: { current: null },
    setSubtitlePosition: jest.fn(),
    setSubtitleSize: jest.fn(),
    setMaxSubtitleLines: jest.fn(),
    setSubtitleColor: jest.fn(),
    subtitlePosition: 16,
    maxSubtitleLines: 1,
    videoInfo: null,
    subtitleColor: '#FFFF00',
    SUBTITLE_COLORS: [],
    subtitleSize: 100,
    previewVideoUrl: null,
    transcriptContainerRef: { current: null },
    isSavingTranscript: false,
    transcriptSaveError: null,
};

describe('Sidebar Tabs', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        (useProcessContext as jest.Mock).mockReturnValue(mockContextValue);
    });

    it('renders all three tabs with icons', () => {
        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.getByRole('tab', { name: /transcript/i })).toBeInTheDocument();
        expect(screen.getByRole('tab', { name: /styles/i })).toBeInTheDocument();
        expect(screen.getByRole('tab', { name: /intelligence/i })).toBeInTheDocument();

        // Check for SVG icons in tabs (they are visible because they are inside the buttons)
        const tabList = screen.getByRole('tablist');
        expect(tabList.parentElement).toHaveClass('editor-tabs-sticky');
        const buttons = screen.getAllByRole('tab');
        buttons.forEach(button => {
            expect(button.querySelector('svg')).toBeInTheDocument();
        });
    });

    it('renders one unique scroll anchor for each transcript cue', () => {
        Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
            configurable: true,
            value: jest.fn(),
        });
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            cues: [{ start: 0, end: 1, text: 'First subtitle' }],
        });

        const { container } = render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        // REGRESSION: nested duplicate cue ids made active-cue scrolling
        // target an ambiguous element inside the clipped transcript region.
        expect(container.querySelectorAll('#cue-0')).toHaveLength(1);
    });

    it('switches to intelligence tab when clicked', () => {
        const setActiveSidebarTab = jest.fn();
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            setActiveSidebarTab,
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        const intelligenceTab = screen.getByRole('tab', { name: /intelligence/i });
        fireEvent.click(intelligenceTab);

        expect(setActiveSidebarTab).toHaveBeenCalledWith('intelligence');
    });

    it('renders ViralIntelligence when activeSidebarTab is intelligence', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            activeSidebarTab: 'intelligence',
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.getByTestId('viral-intelligence')).toBeInTheDocument();
    });

    it('shows manual style settings without preset cards', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            activeSidebarTab: 'styles',
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.getByRole('heading', { name: /custom settings/i })).toBeInTheDocument();
        expect(screen.queryByText('TikTok Pro')).not.toBeInTheDocument();
        expect(screen.queryByText('Cinematic Master')).not.toBeInTheDocument();
        expect(screen.queryByText('Podcast Style')).not.toBeInTheDocument();
        expect(screen.queryByText('Last Used')).not.toBeInTheDocument();
        expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    });
});
