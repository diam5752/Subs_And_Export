import { formatDate, buildStaticUrl } from '../utils';

// Mock API_BASE
jest.mock('../api', () => ({
    API_BASE: 'http://localhost:8000',
}));

describe('utils', () => {
    describe('formatDate', () => {
        it('should format valid date timestamps', () => {
            const timestamp = new Date('2024-01-15T10:30:00Z').getTime();
            const result = formatDate(timestamp);
            expect(result).toContain('2024');
        });

        it('should format valid date strings', () => {
            const result = formatDate('2024-01-15T10:30:00Z');
            expect(result).toContain('2024');
        });

        it('should return original value for invalid dates', () => {
            expect(formatDate('invalid')).toBe('invalid');
            expect(formatDate('')).toBe('');
        });

        it('should handle numeric strings', () => {
            const result = formatDate('1705316400000');
            expect(typeof result).toBe('string');
        });
    });

    describe('buildStaticUrl', () => {
        it('should return null for null/undefined input', () => {
            expect(buildStaticUrl(null)).toBeNull();
            expect(buildStaticUrl(undefined)).toBeNull();
            expect(buildStaticUrl('')).toBeNull();
        });

        it('should handle paths already with /static/ prefix', () => {
            const result = buildStaticUrl('/static/video.mp4');
            expect(result).toBe('http://localhost:8000/static/video.mp4');
        });

        it('should add /static/ prefix to data paths', () => {
            const result = buildStaticUrl('data/artifacts/video.mp4');
            expect(result).toBe('http://localhost:8000/static/artifacts/video.mp4');
        });

        it('should strip host from full URLs', () => {
            const result = buildStaticUrl('https://example.com/static/video.mp4');
            expect(result).toBe('http://localhost:8000/static/video.mp4');
        });

        it('should handle paths with leading slash', () => {
            const result = buildStaticUrl('/data/artifacts/video.mp4');
            expect(result).toBe('http://localhost:8000/static/artifacts/video.mp4');
        });

        it('should handle double static prefix', () => {
            const result = buildStaticUrl('static/static/video.mp4');
            // The function strips one static prefix, so static/static becomes static
            expect(result).toBe('http://localhost:8000/static/static/video.mp4');
        });
    });
});
