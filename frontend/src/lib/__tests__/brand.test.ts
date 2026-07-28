import { BRAND } from '@/lib/brand';

describe('gsubs brand contract', () => {
    it('publishes one canonical product name and asset set', () => {
        expect(BRAND).toEqual({
            name: 'gsubs',
            productTitle: 'gsubs · Subtitle Studio',
            description: 'Turn speech into editable subtitles and export-ready short-form video.',
            assets: {
                logo: '/brand/gsubs-logo.svg',
                mark: '/brand/gsubs-mark.svg',
                watermark: '/gsubs-watermark.png',
                icon: '/icon.png',
                appleIcon: '/apple-icon.png',
            },
        });
    });
});
