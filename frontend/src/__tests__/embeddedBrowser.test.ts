import { isEmbeddedMobileBrowser } from '@/lib/embeddedBrowser';

describe('isEmbeddedMobileBrowser', () => {
    it.each([
        [
            'Messenger on iOS',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 [FBAN/MessengerForiOS;FBAV/520.0.0.0.0]',
        ],
        [
            'Facebook on Android',
            'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Version/4.0 Chrome/138.0.0.0 Mobile Safari/537.36 [FB_IAB/FB4A;]',
        ],
        [
            'generic Android WebView',
            'Mozilla/5.0 (Linux; Android 15; Pixel 9 Build/AP3A; wv) AppleWebKit/537.36 Version/4.0 Chrome/138.0.0.0 Mobile Safari/537.36',
        ],
        [
            'generic iOS WebView',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148',
        ],
    ])('detects %s', (_label, userAgent) => {
        expect(isEmbeddedMobileBrowser(userAgent)).toBe(true);
    });

    it.each([
        [
            'Safari on iOS',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 Version/18.6 Mobile/15E148 Safari/604.1',
        ],
        [
            'Chrome on iOS',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 CriOS/138.0.7204.156 Mobile/15E148 Safari/604.1',
        ],
        [
            'Firefox on Android',
            'Mozilla/5.0 (Android 15; Mobile; rv:141.0) Gecko/141.0 Firefox/141.0',
        ],
        [
            'Chrome on Android',
            'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/138.0.0.0 Mobile Safari/537.36',
        ],
    ])('does not block %s', (_label, userAgent) => {
        expect(isEmbeddedMobileBrowser(userAgent)).toBe(false);
    });

    it('treats an installed standalone mobile web app as a WebView', () => {
        expect(isEmbeddedMobileBrowser('Mozilla/5.0', true)).toBe(true);
    });
});
