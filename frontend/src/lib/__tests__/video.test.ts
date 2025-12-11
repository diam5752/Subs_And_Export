
import { parseResolutionString, describeResolution, describeResolutionString, validateVideoAspectRatio } from '../video';

describe('video utils', () => {
    describe('parseResolutionString', () => {
        it('should parse valid resolution strings', () => {
            expect(parseResolutionString('1920x1080')).toEqual({ width: 1920, height: 1080 });
            expect(parseResolutionString('1280X720')).toEqual({ width: 1280, height: 720 });
            expect(parseResolutionString(' 1080 x 1920 ')).toEqual({ width: 1080, height: 1920 });
            expect(parseResolutionString('1080×1920')).toEqual({ width: 1080, height: 1920 }); // Unicode ×
        });

        it('should return null for invalid strings', () => {
            expect(parseResolutionString('')).toBeNull();
            expect(parseResolutionString(null)).toBeNull();
            expect(parseResolutionString(undefined)).toBeNull();
            expect(parseResolutionString('invalid')).toBeNull();
            expect(parseResolutionString('100x')).toBeNull();
        });
    });

    describe('describeResolution', () => {
        it('should describe standard resolutions correctly', () => {
            expect(describeResolution(3840, 2160)).toEqual({ text: '3840×2160', label: '4K / 2160p' });
            expect(describeResolution(2560, 1440)).toEqual({ text: '2560×1440', label: 'QHD / 1440p' });
            expect(describeResolution(1920, 1080)).toEqual({ text: '1920×1080', label: 'Full HD / 1080p' });
            expect(describeResolution(1280, 720)).toEqual({ text: '1280×720', label: 'HD / 720p' });
            expect(describeResolution(640, 480)).toEqual({ text: '640×480', label: 'SD' });
        });

        it('should return null for invalid dimensions', () => {
            expect(describeResolution(0, 100)).toBeNull();
            expect(describeResolution(100, 0)).toBeNull();
            expect(describeResolution(undefined, 100)).toBeNull();
            expect(describeResolution(100, undefined)).toBeNull();
        });
    });

    describe('describeResolutionString', () => {
        it('should describe valid resolution strings', () => {
            expect(describeResolutionString('1920x1080')).toEqual({ text: '1920×1080', label: 'Full HD / 1080p' });
            expect(describeResolutionString('1080x1920')).toEqual({ text: '1080×1920', label: 'Full HD / 1080p' });
        });

        it('should return null for invalid strings', () => {
            expect(describeResolutionString('')).toBeNull();
            expect(describeResolutionString(null)).toBeNull();
            expect(describeResolutionString('invalid')).toBeNull();
        });
    });

    describe('validateVideoAspectRatio', () => {
        let mockVideo: HTMLVideoElement;
        let mockCanvas: HTMLCanvasElement;
        let mockContext: CanvasRenderingContext2D;
        const events: Record<string, () => void> = {};

        beforeEach(() => {
            events['loadedmetadata'] = () => { };
            events['seeked'] = () => { };
            events['error'] = () => { };

            mockVideo = {
                videoWidth: 0,
                videoHeight: 0,
                duration: 10,
                currentTime: 0,
                preload: '',
                muted: false,
                playsInline: false,
                src: '',
                addEventListener: jest.fn((event, handler) => {
                    events[event] = handler;
                }),
                load: jest.fn(),
                removeAttribute: jest.fn(),
            } as unknown as HTMLVideoElement;

            mockContext = {
                drawImage: jest.fn(),
            } as unknown as CanvasRenderingContext2D;

            mockCanvas = {
                width: 0,
                height: 0,
                getContext: jest.fn(() => mockContext),
                toDataURL: jest.fn(() => 'data:image/jpeg;base64,test'),
            } as unknown as HTMLCanvasElement;

            jest.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
                if (tagName === 'video') return mockVideo;
                if (tagName === 'canvas') return mockCanvas;
                return document.createElement(tagName);
            });

            global.URL.createObjectURL = jest.fn(() => 'blob:test');
            global.URL.revokeObjectURL = jest.fn();
        });

        afterEach(() => {
            jest.restoreAllMocks();
        });

        it('should validate valid 9:16 video', async () => {
            const file = new File([''], 'test.mp4', { type: 'video/mp4' });
            const promise = validateVideoAspectRatio(file);

            (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
            (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
            events['loadedmetadata']();
            events['seeked']();

            const result = await promise;
            expect(result).toEqual({
                width: 1080,
                height: 1920,
                aspectWarning: false,
                thumbnailUrl: 'data:image/jpeg;base64,test',
            });
        });

        it('should warn for non-9:16 video', async () => {
            const file = new File([''], 'test.mp4', { type: 'video/mp4' });
            const promise = validateVideoAspectRatio(file);

            (mockVideo as unknown as { videoWidth: number }).videoWidth = 1920;
            (mockVideo as unknown as { videoHeight: number }).videoHeight = 1080;
            events['loadedmetadata']();
            events['seeked']();

            const result = await promise;
            expect(result.aspectWarning).toBe(true);
        });

        it('should handle video load errors', async () => {
            const file = new File([''], 'test.mp4', { type: 'video/mp4' });
            const promise = validateVideoAspectRatio(file);

            events['error']();

            const result = await promise;
            expect(result).toEqual({
                width: 0,
                height: 0,
                aspectWarning: true,
                thumbnailUrl: null,
            });
        });

        it('should handle captureFrame with no video dimensions', async () => {
            const file = new File([''], 'test.mp4', { type: 'video/mp4' });
            const promise = validateVideoAspectRatio(file);

            // Trigger metadata but leave dimensions at 0
            (mockVideo as unknown as { videoWidth: number }).videoWidth = 0;
            (mockVideo as unknown as { videoHeight: number }).videoHeight = 0;
            events['loadedmetadata']();
            events['seeked']();

            const result = await promise;
            expect(result.thumbnailUrl).toBeNull();
            expect(result.width).toBe(0);
        });

        it('should handle canvas.getContext returning null', async () => {
            mockCanvas.getContext = jest.fn(() => null);

            const file = new File([''], 'test.mp4', { type: 'video/mp4' });
            const promise = validateVideoAspectRatio(file);

            (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
            (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
            events['loadedmetadata']();
            events['seeked']();

            const result = await promise;
            expect(result.thumbnailUrl).toBeNull();
        });

        it('should handle currentTime setter throwing', async () => {
            Object.defineProperty(mockVideo, 'currentTime', {
                set: () => { throw new Error('Seek not supported'); },
                get: () => 0,
            });

            const file = new File([''], 'test.mp4', { type: 'video/mp4' });
            const promise = validateVideoAspectRatio(file);

            (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
            (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
            events['loadedmetadata']();

            const result = await promise;
            expect(result.width).toBe(1080);
        });

        it('should handle video.load throwing', async () => {
            const consoleSpy = jest.spyOn(console, 'warn').mockImplementation(() => { });
            mockVideo.load = jest.fn(() => { throw new Error('Load failed'); });

            const file = new File([''], 'test.mp4', { type: 'video/mp4' });
            const promise = validateVideoAspectRatio(file);

            events['error']();

            const result = await promise;
            expect(result.thumbnailUrl).toBeNull();
            consoleSpy.mockRestore();
        });

        it('should handle short video duration', async () => {
            (mockVideo as unknown as { duration: number }).duration = 0.5; // Less than 1 second

            const file = new File([''], 'test.mp4', { type: 'video/mp4' });
            const promise = validateVideoAspectRatio(file);

            (mockVideo as unknown as { videoWidth: number }).videoWidth = 1080;
            (mockVideo as unknown as { videoHeight: number }).videoHeight = 1920;
            events['loadedmetadata']();
            events['seeked']();

            const result = await promise;
            expect(result.width).toBe(1080);
        });
    });
});
