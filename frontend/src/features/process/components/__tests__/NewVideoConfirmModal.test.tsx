import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import el from '@/i18n/el.json';
import { NewVideoConfirmModal } from '../NewVideoConfirmModal';

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({
        t: (key: keyof typeof el) => el[key] ?? key,
    }),
}));

describe('NewVideoConfirmModal', () => {
    beforeEach(() => {
        jest.useFakeTimers();
    });

    afterEach(() => {
        jest.runOnlyPendingTimers();
        jest.useRealTimers();
    });

    it('accurately explains that the completed video remains in History', () => {
        // REGRESSION: the modal used to claim that the completed video would be
        // permanently deleted even though starting over only resets the editor.
        render(<NewVideoConfirmModal isOpen onClose={jest.fn()} onConfirm={jest.fn()} />);

        expect(screen.getByRole('dialog', { name: 'Νέο project;' })).toHaveTextContent(
            'Το ολοκληρωμένο βίντεο θα παραμείνει στο Ιστορικό',
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

    it('supports Escape, cancel, and explicit confirmation', () => {
        const onClose = jest.fn();
        const onConfirm = jest.fn();
        render(<NewVideoConfirmModal isOpen onClose={onClose} onConfirm={onConfirm} />);

        fireEvent.keyDown(document, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByRole('button', { name: 'Συνέχιση επεξεργασίας' }));
        expect(onClose).toHaveBeenCalledTimes(2);
        expect(onConfirm).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Νέο project' }));
        expect(onConfirm).toHaveBeenCalledTimes(1);
        expect(onClose).toHaveBeenCalledTimes(3);
    });
});
