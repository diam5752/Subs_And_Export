
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ProcessView } from '@/components/ProcessView';
import { JobResponse, api } from '@/lib/api';
import { validateVideoAspectRatio } from '@/lib/video';

// Mock dependencies
jest.mock('@/components/VideoModal', () => ({
    VideoModal: () => <div data-testid="video-modal">VideoModal</div>,
}));
jest.mock('@/components/ViralIntelligence', () => ({
    ViralIntelligence: ({ onGenerate }: any) => <div data-testid="viral-intelligence"><button onClick={onGenerate}>Generate</button></div>,
}));
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));
// Mock video utils
jest.mock('@/lib/video');

// Mock scrollIntoView
window.HTMLElement.prototype.scrollIntoView = jest.fn();

// Mock URL.createObjectURL
global.URL.createObjectURL = jest.fn(() => 'blob:url');
global.URL.revokeObjectURL = jest.fn();

describe('ProcessView', () => {
    const defaultProps = {
        selectedFile: null,
        onFileSelect: jest.fn(),
        isProcessing: false,
        progress: 0,
        statusMessage: '',
        error: '',
        onStartProcessing: jest.fn(),
        onReset: jest.fn(),
        selectedJob: null,
        onJobSelect: jest.fn(),
        recentJobs: [],
        jobsLoading: false,
        statusStyles: {},
        formatDate: (ts: string | number) => String(ts),
        buildStaticUrl: (path?: string | null) => path || null,
        onRefreshJobs: jest.fn(),
    };

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('should show 9:16 aspect ratio warning', async () => {
        // Mock validation to return aspect warning
        (validateVideoAspectRatio as jest.Mock).mockResolvedValue({
            width: 1920,
            height: 1080,
            aspectWarning: true,
            thumbnailUrl: 'blob:thumb'
        });

        const file = new File(['dummy'], 'wide.mp4', { type: 'video/mp4' });

        render(<ProcessView {...defaultProps} selectedFile={file} />);

        await waitFor(() => {
            expect(validateVideoAspectRatio).toHaveBeenCalledWith(file);
            expect(screen.getByText(/Not 9:16/i)).toBeInTheDocument();
        });
    });

    it('should render drop zone when no file is selected', () => {
        render(<ProcessView {...defaultProps} />);
        expect(screen.getByText('uploadDropTitle')).toBeInTheDocument();
    });

    it('should render file details when file is selected', async () => {
        (validateVideoAspectRatio as jest.Mock).mockResolvedValue({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb'
        });

        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });

        render(<ProcessView {...defaultProps} selectedFile={file} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());
        expect(screen.queryByText(/Not 9:16/i)).not.toBeInTheDocument();
    });

    it('should start processing with selected options', async () => {
        (validateVideoAspectRatio as jest.Mock).mockResolvedValue({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb'
        });

        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onStartProcessing = jest.fn();

        render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Settings are open by default, so we don't need to click controlsTitle
        // fireEvent.click(screen.getByText('controlsTitle'));
        fireEvent.click(screen.getByTestId('model-best'));
        fireEvent.click(screen.getByText('controlsStart'));

        expect(onStartProcessing).toHaveBeenCalledWith(expect.objectContaining({
            transcribeMode: 'best',
        }));
    });

    it('should handle download fallback', async () => {
        const completedJob = {
            id: '1', status: 'completed',
            result_data: { public_url: 'http://test.com/video.mp4', original_filename: 'video.mp4' }
        } as JobResponse;

        render(<ProcessView {...defaultProps} selectedJob={completedJob} />);
        expect(screen.getByText('Subtitles Ready')).toBeInTheDocument();
    });

    it('should auto-scroll to results on processing', async () => {
        const { rerender } = render(<ProcessView {...defaultProps} isProcessing={false} />);
        rerender(<ProcessView {...defaultProps} isProcessing={true} />);

        await waitFor(() => expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalled());
    });
});
