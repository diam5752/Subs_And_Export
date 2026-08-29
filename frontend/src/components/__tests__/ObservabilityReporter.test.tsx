import { act, render } from '@testing-library/react';
import { ObservabilityReporter } from '@/components/ObservabilityReporter';
import { useAuth } from '@/context/AuthContext';
import {
    reportBrowserError,
    reportPresence,
    reportProductAction,
} from '@/lib/observability';

jest.mock('@/context/AuthContext', () => ({ useAuth: jest.fn() }));
jest.mock('@/lib/observability', () => ({
    reportBrowserError: jest.fn(),
    reportPresence: jest.fn(),
    reportProductAction: jest.fn(),
}));

describe('ObservabilityReporter', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        jest.useFakeTimers();
        (useAuth as jest.Mock).mockReturnValue({ user: null, isLoading: false });
        Object.defineProperty(document, 'visibilityState', {
            configurable: true,
            value: 'visible',
        });
    });

    afterEach(() => jest.useRealTimers());

    it('reports visible presence and sanitized browser error categories', () => {
        render(<ObservabilityReporter />);

        expect(reportProductAction).toHaveBeenCalledWith('app_opened');
        expect(reportPresence).toHaveBeenCalledTimes(1);
        act(() => jest.advanceTimersByTime(30_000));
        expect(reportPresence).toHaveBeenCalledTimes(2);

        window.dispatchEvent(new Event('error'));
        window.dispatchEvent(new Event('unhandledrejection'));
        expect(reportBrowserError).toHaveBeenCalledWith('window_error');
        expect(reportBrowserError).toHaveBeenCalledWith('unhandled_rejection');
    });

    it('does not heartbeat while the page is hidden', () => {
        Object.defineProperty(document, 'visibilityState', {
            configurable: true,
            value: 'hidden',
        });
        render(<ObservabilityReporter />);
        act(() => jest.advanceTimersByTime(60_000));
        expect(reportPresence).not.toHaveBeenCalled();
    });
});
