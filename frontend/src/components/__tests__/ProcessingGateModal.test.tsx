import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ProcessingGateModal } from '@/components/ProcessingGateModal';
import { useAuth } from '@/context/AuthContext';

jest.mock('@/context/AuthContext', () => ({
    useAuth: jest.fn(),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

describe('ProcessingGateModal', () => {
    const login = jest.fn();
    const register = jest.fn();
    const onAuthenticated = jest.fn();
    const onConfirm = jest.fn();
    const onClose = jest.fn();

    beforeEach(() => {
        jest.clearAllMocks();
        login.mockResolvedValue(undefined);
        register.mockResolvedValue(undefined);
        onAuthenticated.mockResolvedValue(undefined);
        onConfirm.mockResolvedValue(undefined);
        (useAuth as jest.Mock).mockReturnValue({ login, register });
    });

    it('authenticates inline without navigating away from the selected video', async () => {
        render(
            <ProcessingGateModal
                isOpen
                stage="auth"
                cost={25}
                balance={null}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={onConfirm}
            />,
        );

        fireEvent.change(screen.getByLabelText('loginEmailLabel'), { target: { value: 'creator@example.com' } });
        fireEvent.change(screen.getByLabelText('loginPasswordLabel'), { target: { value: 'correct-password' } });
        fireEvent.click(screen.getByRole('button', { name: 'processingGateLoginSubmit' }));

        await waitFor(() => {
            expect(login).toHaveBeenCalledWith('creator@example.com', 'correct-password');
            expect(onAuthenticated).toHaveBeenCalledTimes(1);
        });
        expect(onConfirm).not.toHaveBeenCalled();
    });

    it('supports account creation inside the same gate', async () => {
        render(
            <ProcessingGateModal
                isOpen
                stage="auth"
                cost={25}
                balance={null}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={onConfirm}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: 'processingGateCreateAccount' }));
        fireEvent.change(screen.getByLabelText('registerNameLabel'), { target: { value: 'Creator' } });
        fireEvent.change(screen.getByLabelText('loginEmailLabel'), { target: { value: 'new@example.com' } });
        fireEvent.change(screen.getByLabelText('loginPasswordLabel'), { target: { value: 'twelve-chars!' } });
        fireEvent.click(screen.getByRole('button', { name: 'processingGateRegisterSubmit' }));

        await waitFor(() => {
            expect(register).toHaveBeenCalledWith('new@example.com', 'twelve-chars!', 'Creator');
            expect(onAuthenticated).toHaveBeenCalledTimes(1);
        });
    });

    it('requires an explicit cost confirmation before processing', () => {
        render(
            <ProcessingGateModal
                isOpen
                stage="cost"
                cost={25}
                balance={100}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={onConfirm}
            />,
        );

        expect(screen.getByText('25')).toBeInTheDocument();
        expect(screen.getByText('100')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'processingGateConfirm' }));
        expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it('blocks confirmation when the coin balance is insufficient', () => {
        render(
            <ProcessingGateModal
                isOpen
                stage="cost"
                cost={25}
                balance={10}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={onConfirm}
            />,
        );

        expect(screen.getByRole('alert')).toHaveTextContent('processingGateInsufficient');
        expect(screen.getByRole('button', { name: 'processingGateConfirm' })).toBeDisabled();
    });
});
