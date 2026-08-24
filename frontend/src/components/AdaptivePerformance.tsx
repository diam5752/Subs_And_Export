'use client';

import { useEffect } from 'react';

const CONSTRAINED_DISPLAY_QUERY = '(prefers-reduced-motion: reduce), (update: slow)';

interface NetworkInformationHints {
    saveData?: boolean;
    addEventListener?: (type: 'change', listener: () => void) => void;
    removeEventListener?: (type: 'change', listener: () => void) => void;
}

interface NavigatorPerformanceHints extends Navigator {
    deviceMemory?: number;
    connection?: NetworkInformationHints;
}

interface VisualPerformanceHints {
    constrainedDisplay?: boolean;
    deviceMemory?: number;
    hardwareConcurrency?: number;
    saveData?: boolean;
}

export function shouldReduceVisualEffects(hints: VisualPerformanceHints): boolean {
    const constrainedMemory = typeof hints.deviceMemory === 'number'
        && hints.deviceMemory > 0
        && hints.deviceMemory <= 4;
    const constrainedCpu = typeof hints.hardwareConcurrency === 'number'
        && hints.hardwareConcurrency > 0
        && hints.hardwareConcurrency <= 4;

    return Boolean(
        hints.constrainedDisplay
        || hints.saveData
        || constrainedMemory
        || constrainedCpu
    );
}

export function AdaptivePerformance() {
    useEffect(() => {
        const browserNavigator = navigator as NavigatorPerformanceHints;
        const constrainedDisplay = window.matchMedia(CONSTRAINED_DISPLAY_QUERY);
        const connection = browserNavigator.connection;
        const root = document.documentElement;

        const updateVisualEffects = () => {
            const reduceEffects = shouldReduceVisualEffects({
                constrainedDisplay: constrainedDisplay.matches,
                deviceMemory: browserNavigator.deviceMemory,
                hardwareConcurrency: browserNavigator.hardwareConcurrency,
                saveData: connection?.saveData,
            });
            if (reduceEffects) {
                root.dataset.visualEffects = 'reduced';
            } else {
                delete root.dataset.visualEffects;
            }
        };

        updateVisualEffects();
        if (typeof constrainedDisplay.addEventListener === 'function') {
            constrainedDisplay.addEventListener('change', updateVisualEffects);
        } else {
            constrainedDisplay.addListener(updateVisualEffects);
        }
        connection?.addEventListener?.('change', updateVisualEffects);

        return () => {
            if (typeof constrainedDisplay.removeEventListener === 'function') {
                constrainedDisplay.removeEventListener('change', updateVisualEffects);
            } else {
                constrainedDisplay.removeListener(updateVisualEffects);
            }
            connection?.removeEventListener?.('change', updateVisualEffects);
            delete root.dataset.visualEffects;
        };
    }, []);

    return null;
}
