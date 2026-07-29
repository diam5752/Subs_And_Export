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

// Keep the hidden feature implementation isolated from the navigation tests.
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

    it('renders only the two currently available tabs with icons', () => {
        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.getByRole('tab', { name: /transcript/i })).toBeInTheDocument();
        expect(screen.getByRole('tab', { name: /styles/i })).toBeInTheDocument();
        expect(screen.queryByRole('tab', { name: /intelligence/i })).not.toBeInTheDocument();

        const tabList = screen.getByRole('tablist');
        expect(tabList.parentElement).toHaveClass('editor-tabs-sticky');
        expect(tabList).toHaveClass('editor-tabs-two');
        const buttons = screen.getAllByRole('tab');
        expect(buttons).toHaveLength(2);
        buttons.forEach(button => {
            expect(button.querySelector('svg')).toBeInTheDocument();
        });
    });

    it('starts style controls directly below the tabs without a repeated file header', () => {
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            selectedJob: {
                id: 'test-job',
                result_data: { original_filename: 'sample_subs.mp4' },
            },
            activeSidebarTab: 'styles',
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        // REGRESSION: the filename/status row and repeated "Custom settings"
        // heading consumed the first part of the mobile settings panel.
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
        expect(screen.queryByText('sample_subs.mp4')).not.toBeInTheDocument();
        expect(screen.queryByRole('heading', { name: 'Custom settings' })).not.toBeInTheDocument();
        expect(screen.getByRole('slider', { name: 'Size' })).toBeInTheDocument();
        expect(screen.queryByRole('slider', { name: 'Position' })).not.toBeInTheDocument();
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

    it('brings the live preview into view when styles are opened on mobile', () => {
        const setActiveSidebarTab = jest.fn();
        const scrollIntoView = jest.fn();
        const originalMatchMedia = window.matchMedia;
        const originalScrollIntoView = Element.prototype.scrollIntoView;
        const requestAnimationFrame = jest
            .spyOn(window, 'requestAnimationFrame')
            .mockImplementation((callback) => {
                callback(0);
                return 1;
            });
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            writable: true,
            value: jest.fn((query: string) => ({
                matches: query === '(max-width: 899px)',
            })),
        });
        Element.prototype.scrollIntoView = scrollIntoView;
        const workspace = document.createElement('div');
        workspace.id = 'editor-workspace';
        document.body.appendChild(workspace);
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            setActiveSidebarTab,
        });

        try {
            render(
                <I18nProvider initialLocale="en">
                    <PlaybackProvider>
                        <Sidebar />
                    </PlaybackProvider>
                </I18nProvider>
            );

            fireEvent.click(screen.getByRole('tab', { name: /styles/i }));

            expect(setActiveSidebarTab).toHaveBeenCalledWith('styles');
            expect(scrollIntoView).toHaveBeenCalledWith({
                behavior: 'smooth',
                block: 'start',
            });
        } finally {
            workspace.remove();
            requestAnimationFrame.mockRestore();
            Element.prototype.scrollIntoView = originalScrollIntoView;
            Object.defineProperty(window, 'matchMedia', {
                configurable: true,
                writable: true,
                value: originalMatchMedia,
            });
        }
    });

    it('redirects a stale intelligence selection to styles while the tab is hidden', () => {
        const setActiveSidebarTab = jest.fn();
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            activeSidebarTab: 'intelligence',
            setActiveSidebarTab,
        });

        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        expect(screen.queryByTestId('viral-intelligence')).not.toBeInTheDocument();
        expect(setActiveSidebarTab).toHaveBeenCalledWith('styles');
    });

    it('keeps the full transcript label accessible while exposing a compact mobile label', () => {
        render(
            <I18nProvider initialLocale="en">
                <PlaybackProvider>
                    <Sidebar />
                </PlaybackProvider>
            </I18nProvider>
        );

        const transcriptTab = screen.getByRole('tab', { name: 'Transcript' });
        expect(transcriptTab).toHaveAttribute('aria-label', 'Transcript');
        expect(transcriptTab.querySelector('.editor-tab-label-full'))
            .toHaveTextContent('Transcript');
        expect(transcriptTab.querySelector('.editor-tab-label-short'))
            .toHaveTextContent('Captions');
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

        expect(screen.queryByRole('heading', { name: /custom settings/i })).not.toBeInTheDocument();
        expect(screen.queryByText('TikTok Pro')).not.toBeInTheDocument();
        expect(screen.queryByText('Cinematic Master')).not.toBeInTheDocument();
        expect(screen.queryByText('Podcast Style')).not.toBeInTheDocument();
        expect(screen.queryByText('Last Used')).not.toBeInTheDocument();
        expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    });
});
