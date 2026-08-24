import { render, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import {
    AdaptivePerformance,
    shouldReduceVisualEffects,
} from '@/components/AdaptivePerformance';

describe('AdaptivePerformance', () => {
    const originalHardwareConcurrency = Object.getOwnPropertyDescriptor(
        navigator,
        'hardwareConcurrency',
    );
    const originalMatchMedia = window.matchMedia;

    beforeEach(() => {
        document.documentElement.removeAttribute('data-visual-effects');
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            configurable: true,
            value: 8,
        });
        window.matchMedia = jest.fn().mockReturnValue({
            matches: false,
            media: '(prefers-reduced-motion: reduce), (update: slow)',
            onchange: null,
            addEventListener: jest.fn(),
            removeEventListener: jest.fn(),
            addListener: jest.fn(),
            removeListener: jest.fn(),
            dispatchEvent: jest.fn(),
        });
    });

    afterEach(() => {
        document.documentElement.removeAttribute('data-visual-effects');
        window.matchMedia = originalMatchMedia;
        if (originalHardwareConcurrency) {
            Object.defineProperty(
                navigator,
                'hardwareConcurrency',
                originalHardwareConcurrency,
            );
        }
    });

    it('uses reduced effects for constrained hardware and explicit data saving', () => {
        expect(shouldReduceVisualEffects({ hardwareConcurrency: 4 })).toBe(true);
        expect(shouldReduceVisualEffects({ deviceMemory: 4 })).toBe(true);
        expect(shouldReduceVisualEffects({ saveData: true })).toBe(true);
        expect(shouldReduceVisualEffects({ constrainedDisplay: true })).toBe(true);
    });

    it('keeps full effects when no constrained-device hint is present', () => {
        expect(shouldReduceVisualEffects({
            hardwareConcurrency: 8,
            deviceMemory: 8,
            saveData: false,
            constrainedDisplay: false,
        })).toBe(false);
    });

    it('marks low-end documents before removing the marker on cleanup', async () => {
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            configurable: true,
            value: 2,
        });

        const { unmount } = render(<AdaptivePerformance />);

        await waitFor(() => {
            expect(document.documentElement).toHaveAttribute(
                'data-visual-effects',
                'reduced',
            );
        });

        unmount();
        expect(document.documentElement).not.toHaveAttribute('data-visual-effects');
    });

    it('supports legacy MediaQueryList change listeners', async () => {
        const addListener = jest.fn();
        const removeListener = jest.fn();
        window.matchMedia = jest.fn().mockReturnValue({
            matches: true,
            media: '(prefers-reduced-motion: reduce), (update: slow)',
            addListener,
            removeListener,
        });

        const { unmount } = render(<AdaptivePerformance />);

        await waitFor(() => expect(addListener).toHaveBeenCalledTimes(1));
        expect(document.documentElement).toHaveAttribute(
            'data-visual-effects',
            'reduced',
        );

        unmount();
        expect(removeListener).toHaveBeenCalledTimes(1);
    });
});
