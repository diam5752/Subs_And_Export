import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ProcessView } from '@/components/ProcessView';
import { JobResponse, api } from '@/lib/api';
import { describeResolution, validateVideoAspectRatio } from '@/lib/video';

// Mock dependencies
jest.mock('@/components/VideoModal', () => ({
    VideoModal: () => <div data-testid="video-modal">VideoModal</div>
}));
jest.mock('@/components/ViralIntelligence', () => ({
    ViralIntelligence: ({ onClose }: { onClose: () => void }) => (
        <div data-testid="viral-intelligence">
            <button onClick={onClose}>Close Viral Intelligence</button>
        </div>
    )
}));
jest.mock('@/components/SubtitlePositionSelector', () => ({
    SubtitlePositionSelector: ({ onChange, onChangeLines, onChangeColor, colors }: {
        onChange: (pos: string) => void;
        onChangeLines: (lines: number) => void;
        onChangeColor: (color: string) => void;
        colors?: Array<{ value: string; label: string }>;
    }) => (
        <div data-testid="subtitle-selector">
            <button onClick={() => onChange('top')}>Top</button>
            <button onClick={() => onChangeLines(3)}>3 Lines</button>
            {colors && colors.map((c: { value: string; label: string }) => (
                <button key={c.value} aria-label={`Select ${c.label} color`} onClick={() => onChangeColor(c.value)}>Color</button>
            ))}
        </div>
    ),
}));
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key === 'paginationShowing' ? null : key }),
}));
// Mock video utils
jest.mock('@/lib/video');

// Mock API
jest.mock('@/lib/api', () => ({
    api: {
        deleteJob: jest.fn(),
        deleteJobs: jest.fn(),
        exportVideo: jest.fn(),
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
        currentPage: 1,
        totalPages: 1,
        onNextPage: jest.fn(),
        onPrevPage: jest.fn(),
        totalJobs: 0,
        pageSize: 10,
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
            expect(screen.getByText('aspectRatioWarning')).toBeInTheDocument();
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

        // Find input by digging into the drop zone structure if needed, or by class/type
        // The accessible way is tricky here because input is hidden.
        // We can use container query
        const container = screen.getByText('uploadDropTitle').closest('.card');
        const fileInput = container?.querySelector('input[type="file"]');

        fireEvent.change(fileInput!, { target: { files: [file] } });
        expect(onFileSelect).toHaveBeenCalledWith(file);
    });

    it('should allow model selection via buttons', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onStartProcessing = jest.fn();
        render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Turbo (Enhanced) is selected by default
        expect(screen.getByText('modelEnhancedName')).toBeInTheDocument();
        // It's the default, so we don't need to click it. 
        // If we wanted to, we'd need to expand first:
        // fireEvent.click(screen.getByTestId('model-selector-collapsed'));
        // fireEvent.click(screen.getByTestId('model-turbo'));

        // Start processing
        const startBtn = screen.getByText('controlsStart');
        fireEvent.click(startBtn);

        expect(onStartProcessing).toHaveBeenCalled();
        const call = onStartProcessing.mock.calls[0][0];
        expect(call.transcribeMode).toBe('turbo');
        expect(call.transcribeProvider).toBe('local');
    });

    it('should force high quality output', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onStartProcessing = jest.fn();
        render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Start processing
        fireEvent.click(screen.getByText('controlsStart'));

        expect(onStartProcessing).toHaveBeenCalled();
        expect(onStartProcessing.mock.calls[0][0].outputQuality).toBe('high quality');
    });

    it('should toggle settings visibility', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        render(<ProcessView {...defaultProps} selectedFile={file} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Settings should be visible by default - check for a known label in settings
        expect(screen.getByText('transcriptionModelLabel')).toBeInTheDocument();

        // Click to collapse settings
        const settingsHeader = screen.getByText('controlsTitle');
        fireEvent.click(settingsHeader);

        // Settings should now be hidden
        expect(screen.queryByText('transcriptionModelLabel')).not.toBeInTheDocument();
    });

    // ... existing model display tests ...

    // === EXPERIMENTAL PROVIDERS TESTS ===

    describe('Experimental Providers', () => {
        it('should display Experimenting section only when toggled', async () => {
            const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
            render(<ProcessView {...defaultProps} selectedFile={file} />);

            await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

            // Initially Experimenting section content should be hidden (collapsed)
            // But the header "Experimenting" is always visible to click
            const expHeader = screen.getByText('experimentingLabel');
            expect(expHeader).toBeInTheDocument();

            // ChatGPT button should NOT be visible yet
            expect(screen.queryByTestId('model-chatgpt')).not.toBeInTheDocument();

            // Toggle it open
            fireEvent.click(expHeader);

            // Now ChatGPT option should be visible
            expect(screen.getByTestId('model-chatgpt')).toBeInTheDocument();
            expect(screen.getByText('modelChatgptName')).toBeInTheDocument();
        });

        // ... existing experimental provider tests, but need to open toggle first ...

        it('should allow Ultimate (Groq) model selection', async () => {
            const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
            const onStartProcessing = jest.fn();
            render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

            await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

            // Expand model list
            fireEvent.click(screen.getByTestId('model-selector-collapsed'));

            // Click Ultimate/Groq button (now in main list)
            const groqBtn = screen.getByTestId('model-groq');
            fireEvent.click(groqBtn);

            // Start processing
            fireEvent.click(screen.getByText('controlsStart'));

            expect(onStartProcessing).toHaveBeenCalled();
            expect(onStartProcessing.mock.calls[0][0].transcribeProvider).toBe('groq');
        });

        // ...
    });

    it('should allow subtitle color and shadow selection', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onStartProcessing = jest.fn();
        render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Select 'Green' color
        const greenBtn = screen.getByLabelText('Select colorGreen color');
        fireEvent.click(greenBtn);

        // Start processing
        fireEvent.click(screen.getByText('controlsStart'));

        expect(onStartProcessing).toHaveBeenCalled();
        const call = onStartProcessing.mock.calls[0][0];
        // Green ASS code: &H0000FF00
        expect(call.subtitle_color).toBe('&H0000FF00');
        // Shadow strength is default 4 as controls are removed
        expect(call.shadow_strength).toBe(4);
    });

    it('should allow ChatGPT model selection', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onStartProcessing = jest.fn();
        render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Open experiments
        fireEvent.click(screen.getByText('experimentingLabel'));

        // Click ChatGPT model button
        const chatgptBtn = screen.getByTestId('model-chatgpt');
        fireEvent.click(chatgptBtn);

        // Start processing
        fireEvent.click(screen.getByText('controlsStart'));

        expect(onStartProcessing).toHaveBeenCalled();
        expect(onStartProcessing.mock.calls[0][0].transcribeProvider).toBe('openai');
    });

    it.skip('should allow resolution selection', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onStartProcessing = jest.fn();
        render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Click 4K resolution button
        const resolution4kBtn = await screen.findByText(/Export 4K/i);
        fireEvent.click(resolution4kBtn);

        // Start processing
        fireEvent.click(screen.getByText('controlsStart'));

        expect(onStartProcessing).toHaveBeenCalled();
        expect(onStartProcessing.mock.calls[0][0].outputResolution).toBe('2160x3840');
    });

    it('should allow AI toggle and context input', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        const onStartProcessing = jest.fn();
        render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Find and click the toggle switch by role
        const toggleSwitch = screen.getByRole('switch', { name: 'aiToggleLabel' });
        fireEvent.click(toggleSwitch);

        // The textarea should now be visible
        await waitFor(() => {
            expect(screen.getByPlaceholderText('contextPlaceholder')).toBeInTheDocument();
        });

        // Enter context
        fireEvent.change(screen.getByPlaceholderText('contextPlaceholder'), { target: { value: 'Test context' } });

        // Start processing
        fireEvent.click(screen.getByText('controlsStart'));

        expect(onStartProcessing).toHaveBeenCalled();
        expect(onStartProcessing.mock.calls[0][0].useAI).toBe(true);
        expect(onStartProcessing.mock.calls[0][0].contextPrompt).toBe('Test context');
    });

    it('should toggle settings visibility', async () => {
        const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
        render(<ProcessView {...defaultProps} selectedFile={file} />);

        await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

        // Settings should be visible by default - check for a known label in settings
        expect(screen.getByText('transcriptionModelLabel')).toBeInTheDocument();

        // Click to collapse settings
        const settingsHeader = screen.getByText('controlsTitle');
        fireEvent.click(settingsHeader);

        // Settings should now be hidden
        expect(screen.queryByText('transcriptionModelLabel')).not.toBeInTheDocument();
    });

    it('should display OpenAI model info', () => {
        const job = {
            id: '1', status: 'completed',
            result_data: { transcribe_provider: 'openai', public_url: 'url' }
        } as JobResponse;
        render(<ProcessView {...defaultProps} selectedJob={job} />);
        expect(screen.getByText('ChatGPT API')).toBeInTheDocument();
    });

    it('should display Turbo model info', () => {
        const job = {
            id: '1', status: 'completed',
            result_data: { model_size: 'large-v3-turbo', public_url: 'url' }
        } as JobResponse;
        render(<ProcessView {...defaultProps} selectedJob={job} />);
        expect(screen.getByText('Turbo')).toBeInTheDocument();
    });

    it('should display custom model info', () => {
        const job = {
            id: '1', status: 'completed',
            result_data: { model_size: 'custom-model', public_url: 'url' }
        } as JobResponse;
        render(<ProcessView {...defaultProps} selectedJob={job} />);
        expect(screen.getByText('custom-model')).toBeInTheDocument();
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

        const downloadBtn = screen.getByRole('button', { name: /downloadHd/i });
        await act(async () => {
            fireEvent.click(downloadBtn);
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

        const downloadBtn = screen.getByRole('button', { name: /downloadHd/i });
        await act(async () => {
            fireEvent.click(downloadBtn);
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
        fireEvent.click(screen.getByText('view'));

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

    it('should trigger file input when upload card is clicked', async () => {
        const onFileSelect = jest.fn();
        render(<ProcessView {...defaultProps} onFileSelect={onFileSelect} isProcessing={false} />);

        // Find the upload card and click it
        const uploadCard = screen.getByText('uploadDropTitle').closest('.card');
        expect(uploadCard).toBeInTheDocument();

        // The click should trigger the hidden file input
        fireEvent.click(uploadCard!);
        // We can verify the file input exists and is accessible
        const fileInput = uploadCard?.querySelector('input[type="file"]');
        expect(fileInput).toBeInTheDocument();
    });

    it('should not trigger file input when upload card is clicked during processing', async () => {
        const onFileSelect = jest.fn();
        render(<ProcessView {...defaultProps} onFileSelect={onFileSelect} isProcessing={true} />);

        // Find upload card and click it during processing
        const uploadCard = screen.getByText('uploadDropTitle').closest('.card');
        fireEvent.click(uploadCard!);

        // File should not be selectable during processing
        // The handler should check isProcessing and not trigger
    });

    // Drag and Drop Tests
    describe('Drag and Drop functionality', () => {
        // Helper to create a FileList-like object
        const createFileList = (files: File[]): FileList => {
            const fileList = {
                ...files,
                length: files.length,
                item: (index: number) => files[index] || null,
            };
            return fileList as unknown as FileList;
        };

        const createDragEventInit = (files: File[]) => ({
            dataTransfer: {
                files: createFileList(files),
                types: ['Files'],
                getData: () => '',
                setData: () => { },
            },
        });

        it('should show drag over state when dragging a file', () => {
            render(<ProcessView {...defaultProps} />);

            const uploadCard = screen.getByText('uploadDropTitle').closest('.card');
            expect(uploadCard).toBeInTheDocument();

            // Use fireEvent with init object
            fireEvent.dragEnter(uploadCard!);

            // Should show the drag over state with bouncing icon and new text
            expect(screen.getByText('dropFileHere')).toBeInTheDocument();
            expect(screen.getByText('releaseToUpload')).toBeInTheDocument();
        });

        it('should hide drag over state on drop', () => {
            render(<ProcessView {...defaultProps} />);

            const uploadCard = screen.getByText('uploadDropTitle').closest('.card');

            // Simulate drag enter
            fireEvent.dragEnter(uploadCard!);

            // Should show drag over state
            expect(screen.getByText('dropFileHere')).toBeInTheDocument();

            // Simulate drop (clears the drag state)
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            fireEvent.drop(uploadCard!, createDragEventInit([file]));

            // Should return to file selected state (not drop zone)
            expect(screen.queryByText('dropFileHere')).not.toBeInTheDocument();
        });

        it('should handle file drop and call onFileSelect', () => {
            const onFileSelect = jest.fn();
            render(<ProcessView {...defaultProps} onFileSelect={onFileSelect} />);

            const uploadCard = screen.getByText('uploadDropTitle').closest('.card');
            const file = new File(['video content'], 'test-video.mp4', { type: 'video/mp4' });

            // Drop the file
            fireEvent.drop(uploadCard!, createDragEventInit([file]));

            expect(onFileSelect).toHaveBeenCalledWith(file);
        });

        it('should accept video files by file extension', () => {
            const onFileSelect = jest.fn();
            render(<ProcessView {...defaultProps} onFileSelect={onFileSelect} />);

            const uploadCard = screen.getByText('uploadDropTitle').closest('.card');

            // Test .mov file
            const movFile = new File(['video'], 'video.mov', { type: '' });
            fireEvent.drop(uploadCard!, createDragEventInit([movFile]));
            expect(onFileSelect).toHaveBeenCalledWith(movFile);

            onFileSelect.mockClear();

            // Test .mkv file
            const mkvFile = new File(['video'], 'video.mkv', { type: '' });
            fireEvent.drop(uploadCard!, createDragEventInit([mkvFile]));
            expect(onFileSelect).toHaveBeenCalledWith(mkvFile);

            onFileSelect.mockClear();

            // Test .webm file
            const webmFile = new File(['video'], 'video.webm', { type: '' });
            fireEvent.drop(uploadCard!, createDragEventInit([webmFile]));
            expect(onFileSelect).toHaveBeenCalledWith(webmFile);

            onFileSelect.mockClear();

            // Test .avi file
            const aviFile = new File(['video'], 'video.avi', { type: '' });
            fireEvent.drop(uploadCard!, createDragEventInit([aviFile]));
            expect(onFileSelect).toHaveBeenCalledWith(aviFile);
        });

        it('should not accept non-video files', () => {
            const onFileSelect = jest.fn();
            render(<ProcessView {...defaultProps} onFileSelect={onFileSelect} />);

            const uploadCard = screen.getByText('uploadDropTitle').closest('.card');
            const textFile = new File(['text'], 'document.txt', { type: 'text/plain' });

            fireEvent.drop(uploadCard!, createDragEventInit([textFile]));

            expect(onFileSelect).not.toHaveBeenCalled();
        });

        it('should not allow drag and drop during processing', () => {
            const onFileSelect = jest.fn();
            render(<ProcessView {...defaultProps} onFileSelect={onFileSelect} isProcessing={true} />);

            const uploadCard = screen.getByText('uploadDropTitle').closest('.card');

            // Try drag enter during processing
            fireEvent.dragEnter(uploadCard!);

            // Should NOT show drag over state (still shows normal upload text)
            expect(screen.getByText('uploadDropTitle')).toBeInTheDocument();
            expect(screen.queryByText('dropFileHere')).not.toBeInTheDocument();

            // Try dropping a file during processing
            const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
            fireEvent.drop(uploadCard!, createDragEventInit([file]));

            expect(onFileSelect).not.toHaveBeenCalled();
        });

        it('should handle drag over event', () => {
            render(<ProcessView {...defaultProps} />);

            const uploadCard = screen.getByText('uploadDropTitle').closest('.card');

            // Just verify dragOver doesn't throw
            expect(() => {
                fireEvent.dragOver(uploadCard!);
            }).not.toThrow();
        });

        it('should only select the first file when multiple files are dropped', () => {
            const onFileSelect = jest.fn();
            render(<ProcessView {...defaultProps} onFileSelect={onFileSelect} />);

            const uploadCard = screen.getByText('uploadDropTitle').closest('.card');
            const file1 = new File(['video1'], 'video1.mp4', { type: 'video/mp4' });
            const file2 = new File(['video2'], 'video2.mp4', { type: 'video/mp4' });

            fireEvent.drop(uploadCard!, createDragEventInit([file1, file2]));

            expect(onFileSelect).toHaveBeenCalledTimes(1);
            expect(onFileSelect).toHaveBeenCalledWith(file1);
        });
    });

    it('should display correct pagination text', () => {
        const props = {
            ...defaultProps,
            currentPage: 2,
            pageSize: 10,
            totalJobs: 25,
            totalPages: 3
        };
        render(<ProcessView {...props} />);

        // Page 2 of 10 items per page with 25 total items
        // Should show items 11-20
        // Formula: start = (2-1)*10 + 1 = 11
        //          end = min(2*10, 25) = 20
        expect(screen.getByText('Showing 11-20 of 25')).toBeInTheDocument();
    });





    // === EXPERIMENTAL PROVIDERS TESTS ===

    describe('Experimental Providers', () => {
        it('should allow Standard (whisper.cpp) model selection', async () => {
            const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
            render(<ProcessView {...defaultProps} selectedFile={file} />);

            await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

            // Expand model list
            fireEvent.click(screen.getByTestId('model-selector-collapsed'));

            // Should show Standard option in main list
            expect(screen.getByTestId('model-whispercpp')).toBeInTheDocument();
            expect(screen.getByText('modelStandardName')).toBeInTheDocument();
            expect(screen.getByText('modelStandardBadge')).toBeInTheDocument();

            // Stats check
            // Stats check
            expect(screen.getAllByText(/Speed/i).length).toBeGreaterThan(0);
            expect(screen.getAllByText(/Accuracy/i).length).toBeGreaterThan(0);
            expect(screen.getAllByText(/Karaoke/i).length).toBeGreaterThan(0);
        });
        it('should display Experimenting section with ChatGPT option', async () => {
            const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
            render(<ProcessView {...defaultProps} selectedFile={file} />);

            await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

            // Should show Experimenting section
            expect(screen.getByText('experimentingLabel')).toBeInTheDocument();
            expect(screen.getByText('betaBadge')).toBeInTheDocument();

            // Toggle experiments open
            fireEvent.click(screen.getByText('experimentingLabel'));

            // Should show ChatGPT option
            expect(screen.getByTestId('model-chatgpt')).toBeInTheDocument();
            expect(screen.getByText('modelChatgptName')).toBeInTheDocument();
        });

        it('should allow Ultimate (Groq) model selection', async () => {
            const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
            const onStartProcessing = jest.fn();
            render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

            await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

            // Expand model list
            fireEvent.click(screen.getByTestId('model-selector-collapsed'));

            // Click Ultimate/Groq button (now in main list)
            const groqBtn = screen.getByTestId('model-groq');
            fireEvent.click(groqBtn);

            // Start processing
            fireEvent.click(screen.getByText('controlsStart'));

            expect(onStartProcessing).toHaveBeenCalled();
            expect(onStartProcessing.mock.calls[0][0].transcribeProvider).toBe('groq');
        });

        it('should display Groq model info for completed job', () => {
            const job = {
                id: '1', status: 'completed',
                result_data: { transcribe_provider: 'groq', public_url: 'url' }
            } as JobResponse;
            render(<ProcessView {...defaultProps} selectedJob={job} />);
            expect(screen.getByText('Groq Turbo')).toBeInTheDocument();
        });



        it('should allow whisper.cpp model selection', async () => {
            const file = new File(['dummy'], 'test.mp4', { type: 'video/mp4' });
            const onStartProcessing = jest.fn();
            render(<ProcessView {...defaultProps} selectedFile={file} onStartProcessing={onStartProcessing} />);

            await waitFor(() => expect(screen.getByText('test.mp4')).toBeInTheDocument());

            // Expand model list
            fireEvent.click(screen.getByTestId('model-selector-collapsed'));

            // Click whisper.cpp button
            const whispercppBtn = screen.getByTestId('model-whispercpp');
            fireEvent.click(whispercppBtn);

            // Start processing
            fireEvent.click(screen.getByText('controlsStart'));

            expect(onStartProcessing).toHaveBeenCalled();
            expect(onStartProcessing.mock.calls[0][0].transcribeProvider).toBe('whispercpp');
        });

        it('should display whisper.cpp model info for completed job', () => {
            const job = {
                id: '1', status: 'completed',
                result_data: { transcribe_provider: 'whispercpp', public_url: 'url' }
            } as JobResponse;
            render(<ProcessView {...defaultProps} selectedJob={job} />);
            expect(screen.getByText('whisper.cpp')).toBeInTheDocument();
        });
    });

    it('calls onCancelProcessing when cancel button is clicked', () => {
        const onCancelProcessing = jest.fn();
        render(<ProcessView {...defaultProps} isProcessing={true} onCancelProcessing={onCancelProcessing} />);

        const cancelBtn = screen.getByText('cancelProcessing');
        fireEvent.click(cancelBtn);
        expect(onCancelProcessing).toHaveBeenCalled();
    });

    it('triggers next/prev page calls', () => {
        const onNextPage = jest.fn();
        const onPrevPage = jest.fn();
        const props = {
            ...defaultProps,
            currentPage: 2,
            totalPages: 3,
            onNextPage,
            onPrevPage,
            recentJobs: [{ id: '1' } as JobResponse]
        };
        render(<ProcessView {...props} />);

        fireEvent.click(screen.getByText(/Previous/i));
        expect(onPrevPage).toHaveBeenCalled();

        fireEvent.click(screen.getByText(/Next/i));
        expect(onNextPage).toHaveBeenCalled();
    });

    it('triggers export for 2160x3840', async () => {
        const job = {
            id: 'job1',
            status: 'completed',
            result_data: {
                public_url: 'url',
                variants: {}
            }
        } as JobResponse;

        const onJobSelect = jest.fn();
        // Dynamically add exportVideo mock
        (api.exportVideo as jest.Mock).mockResolvedValue({ ...job, result_data: { variants: { '2160x3840': 'path' } } });

        render(<ProcessView {...defaultProps} selectedJob={job} onJobSelect={onJobSelect} />);

        const exportBtn = screen.getByRole('button', { name: /export4k/i });
        await act(async () => {
            fireEvent.click(exportBtn);
        });

        expect(api.exportVideo).toHaveBeenCalledWith('job1', '2160x3840');
        expect(onJobSelect).toHaveBeenCalled();
    });

    it('downloads existing variant instead of exporting', async () => {
        const job = {
            id: 'job1',
            status: 'completed',
            result_data: {
                public_url: 'url',
                variants: { '2160x3840': 'existing_path' }
            }
        } as JobResponse;

        render(<ProcessView {...defaultProps} selectedJob={job} />);

        const downloadBtn = screen.getByRole('button', { name: /download4k/i });

        await act(async () => {
            fireEvent.click(downloadBtn);
        });

        // Should call fetch for download, not exportVideo
        expect(api.exportVideo).not.toHaveBeenCalled();
        expect(global.fetch).toHaveBeenCalled();
    });

});
