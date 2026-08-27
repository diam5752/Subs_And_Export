import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import el from '@/i18n/el.json';
import { NewVideoConfirmModal } from '../NewVideoConfirmModal';

let mockMissingNewVideoTranslations = false;

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({
        t: (key: keyof typeof el) => mockMissingNewVideoTranslations ? '' : (el[key] ?? key),
    }),
}));

describe('NewVideoConfirmModal', () => {
    beforeEach(() => {
        jest.useFakeTimers();
        mockMissingNewVideoTranslations = false;
    });

    afterEach(() => {
        jest.runOnlyPendingTimers();
        jest.useRealTimers();
    });

    it('accurately explains the temporary History window', () => {
        // REGRESSION: the modal previously implied that completed media stayed
        // indefinitely unless the user manually deleted it.
        render(<NewVideoConfirmModal isOpen onClose={jest.fn()} onConfirm={jest.fn()} />);

        expect(screen.getByRole('dialog', { name: 'Νέο project;' })).toHaveTextContent(
            'Το project θα μείνει στο Ιστορικό μέχρι την αυτόματη διαγραφή του',
        );
        expect(screen.queryByText(/δεν μπορεί να αναιρεθεί/i)).not.toBeInTheDocument();
    });

    it('focuses the safe action instead of the destructive confirmation', () => {
        render(<NewVideoConfirmModal isOpen onClose={jest.fn()} onConfirm={jest.fn()} />);

        act(() => {
            jest.advanceTimersByTime(100);
        });

        expect(screen.getByRole('button', { name: 'Συνέχιση επεξεργασίας' })).toHaveFocus();
        expect(screen.getByRole('button', { name: 'Νέο project' })).not.toHaveFocus();
    });

    it('keeps safe focus when its parent rerenders with a new close callback', () => {
        // REGRESSION: polling rerenders replaced the inline close callback,
        // which tore down focus management and briefly focused the page behind
        // the open modal.
        const view = render(
            <NewVideoConfirmModal isOpen onClose={jest.fn()} onConfirm={jest.fn()} />,
        );
        act(() => {
            jest.advanceTimersByTime(100);
        });
        const safeAction = screen.getByRole('button', { name: 'Συνέχιση επεξεργασίας' });
        expect(safeAction).toHaveFocus();

        view.rerender(
            <NewVideoConfirmModal isOpen onClose={jest.fn()} onConfirm={jest.fn()} />,
        );

        expect(safeAction).toHaveFocus();
    });

    it('locks and restores both document scrollers', () => {
        window.scrollTo = jest.fn();
        const view = render(
            <NewVideoConfirmModal isOpen onClose={jest.fn()} onConfirm={jest.fn()} />,
        );

        expect(document.documentElement.style.overflow).toBe('hidden');
        expect(document.body.style.overflow).toBe('hidden');
        expect(document.body.style.position).toBe('fixed');

        view.unmount();
        expect(document.documentElement.style.overflow).toBe('');
        expect(document.body.style.overflow).toBe('');
        expect(document.body.style.position).toBe('');
    });

    it('supports Escape, cancel, and explicit confirmation', () => {
        const onClose = jest.fn();
        const onConfirm = jest.fn();
        render(<NewVideoConfirmModal isOpen onClose={onClose} onConfirm={onConfirm} />);

        fireEvent.keyDown(document, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);

        fireEvent.keyDown(document, { key: 'Enter' });
        fireEvent.click(screen.getByRole('dialog').firstElementChild!);
        expect(onClose).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByRole('button', { name: 'Συνέχιση επεξεργασίας' }));
        expect(onClose).toHaveBeenCalledTimes(2);
        expect(onConfirm).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Νέο project' }));
        expect(onConfirm).toHaveBeenCalledTimes(1);
        expect(onClose).toHaveBeenCalledTimes(3);
    });

    it('keeps safe English labels when translations are unavailable', () => {
        mockMissingNewVideoTranslations = true;
        render(<NewVideoConfirmModal isOpen onClose={jest.fn()} onConfirm={jest.fn()} />);

        expect(screen.getByRole('dialog', { name: 'Start a new project?' })).toHaveTextContent(
            'This closes the current editing view.',
        );
        expect(screen.getByRole('button', { name: 'Keep Working' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Start Fresh' })).toBeInTheDocument();
    });

    it('cleans up safely when there was no previously focused element', () => {
        Object.defineProperty(document, 'activeElement', {
            configurable: true,
            get: () => null,
        });
        try {
            const view = render(
                <NewVideoConfirmModal isOpen onClose={jest.fn()} onConfirm={jest.fn()} />,
            );
            view.unmount();
        } finally {
            Reflect.deleteProperty(document, 'activeElement');
        }
    });
});
