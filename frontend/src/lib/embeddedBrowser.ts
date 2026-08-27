const SOCIAL_IN_APP_BROWSER =
    /(?:FBAN|FBAV|FB_IAB|FBIOS|MessengerForiOS|Instagram|Threads|Line\/|MicroMessenger)/i;

const IOS_DEVICE = /(?:iPhone|iPad|iPod)/i;
const IOS_BROWSER = /(?:Safari\/|CriOS\/|FxiOS\/|EdgiOS\/|OPiOS\/|DuckDuckGo\/)/i;

/**
 * Google Identity Services does not support Android or iOS WebViews. Detect
 * the common social-app browsers plus generic mobile WebView signatures so we
 * can keep users out of the blank/blocked accounts.google.com flow.
 */
export function isEmbeddedMobileBrowser(
    userAgent: string,
    standalone = false,
): boolean {
    if (standalone || SOCIAL_IN_APP_BROWSER.test(userAgent)) {
        return true;
    }

    const isAndroidWebView = /Android/i.test(userAgent) && (
        /(?:^|[;\s])wv(?:[);\s]|$)/i.test(userAgent)
        || (
            /Version\/[\d.]+/i.test(userAgent)
            && /Chrome\/[\d.]+/i.test(userAgent)
            && /Mobile Safari\/[\d.]+/i.test(userAgent)
        )
    );
    if (isAndroidWebView) {
        return true;
    }

    return IOS_DEVICE.test(userAgent)
        && /AppleWebKit\//i.test(userAgent)
        && !IOS_BROWSER.test(userAgent);
}
