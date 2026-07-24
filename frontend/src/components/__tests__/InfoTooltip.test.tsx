import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { InfoTooltip } from '@/components/InfoTooltip';

describe('InfoTooltip', () => {
    it('shows tooltip on focus and hides on blur', () => {
        render(
            <InfoTooltip ariaLabel="Info: Example">
                <div>Helpful text</div>
            </InfoTooltip>
        );

        const button = screen.getByRole('button', { name: 'Info: Example' });
        expect(button).toBeInTheDocument();
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

        fireEvent.focus(button);
        expect(screen.getByRole('tooltip')).toHaveTextContent('Helpful text');

        fireEvent.blur(button);
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });

    it('moves above the anchor near the viewport edge and responds to Escape', () => {
        const rectSpy = jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
            if (this.getAttribute('role') === 'tooltip') {
                return { top: 0, bottom: 100, left: 0, right: 240, width: 240, height: 100, x: 0, y: 0, toJSON: () => ({}) };
            }
            return { top: 700, bottom: 720, left: 10, right: 30, width: 20, height: 20, x: 10, y: 700, toJSON: () => ({}) };
        });
        const originalInnerHeight = window.innerHeight;
        Object.defineProperty(window, 'innerHeight', { configurable: true, value: 760 });

        try {
            render(<InfoTooltip ariaLabel="Position help">Top content</InfoTooltip>);
            const button = screen.getByRole('button', { name: 'Position help' });
            fireEvent.focus(button);

            const tooltip = screen.getByRole('tooltip');
            expect(tooltip).toHaveStyle({ top: '592px' });
            fireEvent.keyDown(button, { key: 'Escape' });
            expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
        } finally {
            rectSpy.mockRestore();
            Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalInnerHeight });
        }
    });

    it('observes tooltip size and removes window listeners on close', () => {
        const observe = jest.fn();
        const disconnect = jest.fn();
        const OriginalResizeObserver = global.ResizeObserver;
        global.ResizeObserver = class ResizeObserverMock {
            observe = observe;
            disconnect = disconnect;
            unobserve = jest.fn();
        } as unknown as typeof ResizeObserver;

        try {
            render(<InfoTooltip ariaLabel="Responsive help">Responsive content</InfoTooltip>);
            const button = screen.getByRole('button', { name: 'Responsive help' });
            fireEvent.mouseEnter(button);
            expect(observe).toHaveBeenCalledWith(screen.getByRole('tooltip'));

            fireEvent(window, new Event('resize'));
            fireEvent.mouseLeave(screen.getByRole('tooltip'));

            expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
            expect(disconnect).toHaveBeenCalled();
        } finally {
            global.ResizeObserver = OriginalResizeObserver;
        }
    });
});
