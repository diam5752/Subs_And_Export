import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { Sidebar } from '../components/Sidebar';
import { I18nProvider } from '@/context/I18nContext';
import { useProcessContext } from '../ProcessContext';

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
    editingCueDraft: '',
    handleUpdateDraft: jest.fn(),
    beginEditingCue: jest.fn(),
    saveEditingCue: jest.fn(),
    cancelEditingCue: jest.fn(),
    playerRef: { current: null },
    STYLE_PRESETS: [],
    activePreset: null,
    setActivePreset: jest.fn(),
    setSubtitlePosition: jest.fn(),
    setSubtitleSize: jest.fn(),
    setMaxSubtitleLines: jest.fn(),
    setSubtitleColor: jest.fn(),
    setKaraokeEnabled: jest.fn(),
    lastUsedSettings: null,
    subtitlePosition: 16,
    maxSubtitleLines: 1,
    videoInfo: null,
    subtitleColor: '#FFFF00',
    SUBTITLE_COLORS: [],
    subtitleSize: 100,
    karaokeEnabled: false,
    AVAILABLE_MODELS: [],
    transcribeProvider: 'groq',
    transcribeMode: 'standard',
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
                <Sidebar />
            </I18nProvider>
        );

        expect(screen.getByRole('tab', { name: /transcript/i })).toBeInTheDocument();
        expect(screen.getByRole('tab', { name: /styles/i })).toBeInTheDocument();
        expect(screen.getByRole('tab', { name: /intelligence/i })).toBeInTheDocument();

        // Check for SVG icons in tabs (they are visible because they are inside the buttons)
        const buttons = screen.getAllByRole('tab');
        buttons.forEach(button => {
            expect(button.querySelector('svg')).toBeInTheDocument();
        });
    });

    it('switches to intelligence tab when clicked', () => {
        const setActiveSidebarTab = jest.fn();
        (useProcessContext as jest.Mock).mockReturnValue({
            ...mockContextValue,
            setActiveSidebarTab,
        });

        render(
            <I18nProvider initialLocale="en">
                <Sidebar />
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
                <Sidebar />
            </I18nProvider>
        );

        expect(screen.getByTestId('viral-intelligence')).toBeInTheDocument();
    });
});
