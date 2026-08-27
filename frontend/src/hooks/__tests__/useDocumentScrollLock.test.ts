import { act, renderHook } from '@testing-library/react';
import { useDocumentScrollLock } from '@/hooks/useDocumentScrollLock';

describe('useDocumentScrollLock', () => {
    beforeEach(() => {
        document.documentElement.removeAttribute('style');
        document.body.removeAttribute('style');
        Object.defineProperty(window, 'scrollX', { configurable: true, value: 12 });
        Object.defineProperty(window, 'scrollY', { configurable: true, value: 34 });
        window.scrollTo = jest.fn();
    });

    it('does not mutate either scroller when the lock is disabled', () => {
        const { unmount } = renderHook(() => useDocumentScrollLock(false));

        expect(document.body.style.position).toBe('');
        expect(document.documentElement.style.overflow).toBe('');
        expect(window.scrollTo).not.toHaveBeenCalled();
        unmount();
    });

    it('locks both browser scrollers at an explicit position and restores prior styles', () => {
        document.documentElement.style.overflow = 'clip';
        document.documentElement.style.scrollBehavior = 'smooth';
        document.body.style.overflow = 'auto';
        const { unmount } = renderHook(() => useDocumentScrollLock(true, { x: 5, y: 9 }));

        expect(document.documentElement.style.overflow).toBe('hidden');
        expect(document.body.style.position).toBe('fixed');
        expect(document.body.style.left).toBe('-5px');
        expect(document.body.style.top).toBe('-9px');

        act(() => window.dispatchEvent(new Event('scroll')));
        expect(window.scrollTo).toHaveBeenCalledWith(5, 9);
        unmount();

        expect(document.documentElement.style.overflow).toBe('clip');
        expect(document.documentElement.style.scrollBehavior).toBe('smooth');
        expect(document.body.style.overflow).toBe('auto');
        expect(document.body.style.position).toBe('');
        expect(window.scrollTo).toHaveBeenLastCalledWith(5, 9);
    });

    it('reuses finite coordinates from an existing fixed-body lock', () => {
        document.body.style.position = 'fixed';
        document.body.style.left = '-22px';
        document.body.style.top = '-44px';
        const { unmount } = renderHook(() => useDocumentScrollLock(true));

        expect(document.body.style.left).toBe('-22px');
        expect(document.body.style.top).toBe('-44px');
        unmount();
        expect(window.scrollTo).toHaveBeenLastCalledWith(22, 44);
    });

    it('falls back to window coordinates when an existing lock has invalid offsets', () => {
        document.body.style.position = 'fixed';
        document.body.style.left = 'auto';
        document.body.style.top = 'auto';
        const { unmount } = renderHook(() => useDocumentScrollLock(true));

        expect(document.body.style.left).toBe('-12px');
        expect(document.body.style.top).toBe('-34px');
        unmount();
        expect(window.scrollTo).toHaveBeenLastCalledWith(12, 34);
    });
});
