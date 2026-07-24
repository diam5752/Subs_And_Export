import {
    buildSubtitleExportFilename,
    withDownloadParameters,
} from '@/lib/exportFilename';

describe('buildSubtitleExportFilename', () => {
    it('keeps the original stem and appends _subs for video and subtitle exports', () => {
        // REGRESSION: downloads used the internal processed_<resolution> filename.
        expect(buildSubtitleExportFilename('E Isous.mp4', '1080x1920')).toBe('E Isous_subs.mp4');
        expect(buildSubtitleExportFilename('συνέντευξη.final.MOV', 'srt')).toBe('συνέντευξη.final_subs.srt');
    });

    it('removes path and header-unsafe filename characters with a stable fallback', () => {
        expect(buildSubtitleExportFilename('../folder/bad:name?.mkv', 'vtt')).toBe('bad_name__subs.vtt');
        expect(buildSubtitleExportFilename('..', 'txt')).toBe('video_subs.txt');
        expect(buildSubtitleExportFilename(null, '2160x3840')).toBe('video_subs.mp4');
    });
});

describe('withDownloadParameters', () => {
    it('adds an encoded filename while preserving existing query parameters and fragments', () => {
        expect(withDownloadParameters('/static/video.mp4?token=1#preview', 'Ε Isous_subs.mp4'))
            .toBe('/static/video.mp4?token=1&download=true&filename=%CE%95%20Isous_subs.mp4#preview');
    });
});
