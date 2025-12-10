import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ProcessView, ProcessingOptions } from '@/components/ProcessView';
import { JobResponse, api } from '@/lib/api';
import { describeResolution, validateVideoAspectRatio, describeResolutionString } from '@/lib/video';

// Mock dependencies
jest.mock('@/components/VideoModal', () => ({
    VideoModal: () => <div data-testid="video-modal">VideoModal</div>
}));
jest.mock('@/components/ViralIntelligence', () => ({
    ViralIntelligence: ({ onClose }: any) => (
        <div data-testid="viral-intelligence">
            <button onClick={onClose}>Close Viral Intelligence</button>
        </div>
    )
}));
jest.mock('@/components/SubtitlePositionSelector', () => ({
    SubtitlePositionSelector: ({ onChange, onChangeLines }: any) => (
        <div data-testid="subtitle-selector">
            <button onClick={() => onChange('top')}>Top</button>
            <button onClick={() => onChangeLines(3)}>3 Lines</button>
        </div>
    ),
}));
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));
// Mock video utils
jest.mock('@/lib/video');

// Mock API
jest.mock('@/lib/api', () => ({
    api: {
        deleteJob: jest.fn(),
    },
}));

// Mock scrollIntoView
window.HTMLElement.prototype.scrollIntoView = jest.fn();

// Mock URL and fetch
global.URL.createObjectURL = jest.fn(() => 'blob:url');
global.URL.revokeObjectURL = jest.fn();
global.fetch = jest.fn();
window.open = jest.fn();

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
        (validateVideoAspectRatio as jest.Mock).mockResolvedValue({
            width: 1080,
            height: 1920,
            aspectWarning: false,
            thumbnailUrl: 'blob:thumb'
        });
    });

    it('should show 9:16 aspect ratio warning', async () => {
        (validateVideoAspectRatio as jest.Mock).mockResolvedValue({
            width: 1920,
            height: 1080,
            aspectWarning: true,
            thumbnailUrl: 'blob:thumb'
        });
        const file = new File(['dummy'], 'wide.mp4', { type: 'video/mp4' });

        render(<ProcessView {...defaultProps} selectedFile={file} />);

        await waitFor(() => {
            expect(screen.getByText(/Not 9:16/i)).toBeInTheDocument();
        });
    });

    it('should render drop zone when no file is selected', () => {
        render(<ProcessView {...defaultProps} />);
        expect(screen.getByText('uploadDropTitle')).toBeInTheDocument();
    });

    it('should upload file via input change', async () => {
        const onFileSelect = jest.fn();
        render(<ProcessView {...defaultProps} onFileSelect={onFileSelect} />);

        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const input = screen.getByText('uploadDropTitle').closest('div.card')?.querySelector('input') as HTMLInputElement;

        // Find input by digging into the drop zone structure if needed, or by class/type
        // The accessible way is tricky here because input is hidden.
        // We can use container query
        const container = screen.getByText('uploadDropTitle').closest('.card');
        const fileInput = container?.querySelector('input[type="file"]');

        fireEvent.change(fileInput!, { target: { files: [file] } });
        expect(onFileSelect).toHaveBeenCalledWith(file);
    });

    it.skip('should handle settings interactions', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onStartProcessing = jest.fn();
        render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Toggle Settings (should be open by default, verify closing)
        fireEvent.click(screen.getByText('controlsTitle').closest('.group')!);
        // expect(screen.queryByText('Transcription Model')).not.toBeInTheDocument(); // This might be animated, so just check toggle logic

        // Re-open
        fireEvent.click(screen.getByText('controlsTitle').closest('.group')!);

        // Change Model
        fireEvent.click(screen.getByTestId('model-chatgpt'));
        fireEvent.click(screen.getByTestId('model-best'));

        // Change Quality
        fireEvent.click(screen.getByText('low size'));

        // Change Resolution
        fireEvent.click(screen.getByText('resolution4k'));

        // Toggle AI
        fireEvent.click(screen.getByText('aiToggleLabel'));
        fireEvent.change(screen.getByPlaceholderText('contextPlaceholder'), { target: { value: 'My Prompt' } });

        // Change Subtitle Props
        fireEvent.click(screen.getByText('Top'));
        fireEvent.click(screen.getByText('3 Lines'));

        // Start
        fireEvent.click(screen.getByText('controlsStart'));

        expect(onStartProcessing).toHaveBeenCalledWith({
            transcribeMode: 'best',
            transcribeProvider: 'local',
            outputQuality: 'low size',
            outputResolution: '2160x3840',
            useAI: true,
            contextPrompt: 'My Prompt',
            subtitle_position: 'top',
            max_subtitle_lines: 3
        });
    });



    it('should handle reset', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onReset = jest.fn();
        render(<ProcessView {...defaultProps} selectedFile={file} onReset={onReset} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        fireEvent.click(screen.getByText('processingReset'));
        expect(onReset).toHaveBeenCalled();
    });

    it('should handle download success', async () => {
        const completedJob = {
            id: '1', status: 'completed',
            result_data: { public_url: 'http://test.com/video.mp4', original_filename: 'video.mp4' }
        } as JobResponse;

        (global.fetch as jest.Mock).mockResolvedValue({
            blob: () => Promise.resolve(new Blob(['video data'])),
        });

        render(<ProcessView {...defaultProps} selectedJob={completedJob} />);

        const downloadBtn = screen.getByText(/Download MP4/i).closest('button');
        await act(async () => {
            fireEvent.click(downloadBtn!);
        });

        expect(global.fetch).toHaveBeenCalledWith('http://test.com/video.mp4');
        expect(global.URL.createObjectURL).toHaveBeenCalled();
    });

    it('should handle download error fallback', async () => {
        const completedJob = {
            id: '1', status: 'completed',
            result_data: { public_url: 'http://test.com/video.mp4', original_filename: 'video.mp4' }
        } as JobResponse;

        (global.fetch as jest.Mock).mockRejectedValue(new Error('Network error'));
        const openSpy = jest.spyOn(window, 'open');

        render(<ProcessView {...defaultProps} selectedJob={completedJob} />);

        const downloadBtn = screen.getByText(/Download MP4/i).closest('button');
        await act(async () => {
            fireEvent.click(downloadBtn!);
        });

        expect(openSpy).toHaveBeenCalledWith('http://test.com/video.mp4', '_blank');
    });

    it('should handle job deletion', async () => {
        const job = { id: 'job1', status: 'completed', result_data: { public_url: 'url' } } as JobResponse;
        const onRefreshJobs = jest.fn().mockResolvedValue(undefined);
        const onJobSelect = jest.fn();

        render(<ProcessView
            {...defaultProps}
            recentJobs={[job]}
            onRefreshJobs={onRefreshJobs}
            selectedJob={job}
            onJobSelect={onJobSelect}
        />);

        // Click delete icon
        fireEvent.click(screen.getByTitle('deleteJob'));

        // Confirm should appear
        const confirmBtn = screen.getByText('✓');
        fireEvent.click(confirmBtn);

        await waitFor(() => expect(api.deleteJob).toHaveBeenCalledWith('job1'));
        expect(onRefreshJobs).toHaveBeenCalled();
        expect(onJobSelect).toHaveBeenCalledWith(null); // Should deselect if detecting deleted job
    });

    it.skip('should show preview modal', () => {
        const job = { id: 'job1', status: 'completed', result_data: { public_url: 'url' } } as JobResponse;
        render(<ProcessView {...defaultProps} selectedJob={job} />);

        fireEvent.click(screen.getByText(/Preview/i).closest('button')!);
        expect(screen.getByTestId('video-modal')).toBeInTheDocument();
    });

    it('should handle job deletion failure', async () => {
        const job = { id: 'job1', status: 'completed', result_data: { public_url: 'url' } } as JobResponse;
        const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => { });
        (api.deleteJob as jest.Mock).mockRejectedValue(new Error('Delete error'));

        render(<ProcessView
            {...defaultProps}
            recentJobs={[job]}
            selectedJob={job}
        />);

        fireEvent.click(screen.getByTitle('deleteJob'));
        fireEvent.click(screen.getByText('✓'));

        await waitFor(() => expect(api.deleteJob).toHaveBeenCalled());
        expect(consoleSpy).toHaveBeenCalledWith('Delete failed:', expect.any(Error));
        consoleSpy.mockRestore();
    });

    it.skip('should derive output resolution from video metadata', async () => {
        const job = { id: 'job1', status: 'completed', result_data: { public_url: 'url' } } as JobResponse;

        // Setup mock return
        (describeResolution as jest.Mock).mockReturnValue({ text: '1920x1080', label: 'HD' });

        const originalCreateElement = document.createElement.bind(document);
        const createdVideos: HTMLVideoElement[] = [];

        jest.spyOn(document, 'createElement').mockImplementation((tagName) => {
            const element = originalCreateElement(tagName);
            if (tagName === 'video') {
                createdVideos.push(element as HTMLVideoElement);
            }
            return element;
        });

        render(<ProcessView {...defaultProps} selectedJob={job} />);

        // Find the video used for metadata (it will have src 'url')
        // We might need to wait for useEffect to run
        await waitFor(() => {
            // Check if any video has the src set
            const targetVideo = createdVideos.find(v => v.src.endsWith('url'));
            if (!targetVideo) throw new Error('Video not created yet');

            // Patch and trigger
            Object.defineProperty(targetVideo, 'videoWidth', { value: 1920, configurable: true });
            Object.defineProperty(targetVideo, 'videoHeight', { value: 1080, configurable: true });

            // Dispatch event
            targetVideo.dispatchEvent(new Event('loadedmetadata'));
        });

        await waitFor(() => {
            expect(describeResolution).toHaveBeenCalled();
            expect(screen.getByText('1920x1080')).toBeInTheDocument();
        });
    });

    it('should view job preview', () => {
        const job = { id: 'job1', status: 'completed', result_data: { public_url: 'url' } } as JobResponse;
        const onJobSelect = jest.fn();

        render(<ProcessView {...defaultProps} recentJobs={[job]} onJobSelect={onJobSelect} />);

        // Find View button (secondary button inside the expired check block)
        fireEvent.click(screen.getByText('View'));

        expect(onJobSelect).toHaveBeenCalledWith(job);
        expect(screen.getByTestId('video-modal')).toBeInTheDocument();
    });

    it('should cancel delete confirmation', () => {
        const job = { id: 'job1', status: 'completed', result_data: { public_url: 'url' } } as JobResponse;
        render(<ProcessView {...defaultProps} recentJobs={[job]} />);

        // Click delete to show confirmation
        fireEvent.click(screen.getByTitle('deleteJob'));
        expect(screen.getByText('✓')).toBeInTheDocument();

        // Click Cancel (X)
        fireEvent.click(screen.getByText('✕'));

        expect(screen.queryByText('✓')).not.toBeInTheDocument();
        expect(screen.getByTitle('deleteJob')).toBeInTheDocument();
    });

    it('should scroll to results on processing', async () => {
        const { rerender } = render(<ProcessView {...defaultProps} isProcessing={false} />);
        rerender(<ProcessView {...defaultProps} isProcessing={true} />);

        await waitFor(() => expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalled());
    });

    it('should handle validation race condition', async () => {
        // Test that if file changes rapidly, only latest result is used.
        // This is hard to deterministically test without exposing internal state, 
        // but we can verify that rapid file changes don't crash and eventually show correct one.

        const file1 = new File([''], 'file1.mp4', { type: 'video/mp4' });
        const file2 = new File([''], 'file2.mp4', { type: 'video/mp4' });

        const { rerender } = render(<ProcessView {...defaultProps} selectedFile={file1} />);
        rerender(<ProcessView {...defaultProps} selectedFile={file2} />);

        await waitFor(() => expect(validateVideoAspectRatio).toHaveBeenCalledWith(file2));
    });
});
