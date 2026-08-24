import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ProcessingGateModal } from '@/components/ProcessingGateModal';
import { useAuth } from '@/context/AuthContext';

jest.mock('@/context/AuthContext', () => ({
    useAuth: jest.fn(),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

describe('ProcessingGateModal focus management', () => {
    const onClose = jest.fn();
    const onAuthenticated = jest.fn().mockResolvedValue(undefined);
    const onConfirm = jest.fn().mockResolvedValue(undefined);
    let clientRectsSpy: jest.SpyInstance;

    beforeEach(() => {
        jest.clearAllMocks();
        Object.defineProperty(window, 'scrollTo', {
            configurable: true,
            value: jest.fn(),
            writable: true,
        });
        Object.defineProperty(window, 'scrollX', {
            configurable: true,
            value: 0,
        });
        Object.defineProperty(window, 'scrollY', {
            configurable: true,
            value: 0,
        });
        (useAuth as jest.Mock).mockReturnValue({
            login: jest.fn(),
            register: jest.fn(),
        });
        clientRectsSpy = jest.spyOn(HTMLElement.prototype, 'getClientRects')
            .mockReturnValue([{} as DOMRect] as unknown as DOMRectList);
    });

    afterEach(() => {
        clientRectsSpy.mockRestore();
        document.querySelector('[data-testid="focus-launch-control"]')?.remove();
    });

    it('traps keyboard focus and restores the launch control after closing', async () => {
        const launchButton = document.createElement('button');
        launchButton.dataset.testid = 'focus-launch-control';
        launchButton.textContent = 'launch';
        document.body.appendChild(launchButton);
        launchButton.focus();

        const view = render(
            <ProcessingGateModal
                isOpen
                stage="cost"
                cost={30}
                balance={100}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={onConfirm}
            />,
        );

        const confirmButton = screen.getByRole('button', {
            name: 'processingGateConfirm',
        });
        await waitFor(() => expect(confirmButton).toHaveFocus());

        const dialog = screen.getByTestId('processing-gate-card');
        const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), input:not([disabled]), '
            + 'select:not([disabled]), textarea:not([disabled]), '
            + '[tabindex]:not([tabindex="-1"])',
        ));
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        last.focus();
        fireEvent.keyDown(document, { key: 'Tab' });
        expect(first).toHaveFocus();

        first.focus();
        fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
        expect(last).toHaveFocus();

        view.rerender(
            <ProcessingGateModal
                isOpen={false}
                stage="cost"
                cost={30}
                balance={100}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={onConfirm}
            />,
        );

        await waitFor(() => expect(launchButton).toHaveFocus());
    });

    it('submits the processing confirmation only once while it is in flight', async () => {
        let resolveConfirmation: (() => void) | null = null;
        const pendingConfirmation = new Promise<void>((resolve) => {
            resolveConfirmation = resolve;
        });
        const confirm = jest.fn(() => pendingConfirmation);

        render(
            <ProcessingGateModal
                isOpen
                stage="cost"
                cost={30}
                balance={100}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={confirm}
            />,
        );

        const confirmButton = screen.getByRole('button', {
            name: 'processingGateConfirm',
        });
        fireEvent.click(confirmButton);
        fireEvent.click(confirmButton);

        expect(confirm).toHaveBeenCalledTimes(1);
        expect(confirmButton).toBeDisabled();
        expect(confirmButton).toHaveAttribute('aria-busy', 'true');

        await act(async () => {
            resolveConfirmation?.();
            await pendingConfirmation;
        });

        expect(confirmButton).not.toBeDisabled();
        expect(confirmButton).toHaveAttribute('aria-busy', 'false');
    });
});
