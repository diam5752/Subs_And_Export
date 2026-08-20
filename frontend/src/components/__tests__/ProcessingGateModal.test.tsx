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

describe('ProcessingGateModal', () => {
    const login = jest.fn();
    const register = jest.fn();
    const onAuthenticated = jest.fn();
    const onConfirm = jest.fn();
    const onClose = jest.fn();
    const onPurchaseCredits = jest.fn();

    beforeEach(() => {
        jest.clearAllMocks();
        login.mockResolvedValue(undefined);
        register.mockResolvedValue(undefined);
        onAuthenticated.mockResolvedValue(undefined);
        onConfirm.mockResolvedValue(undefined);
        (useAuth as jest.Mock).mockReturnValue({ login, register });
    });

    afterEach(() => {
        jest.useRealTimers();
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
        const loginButton = screen.getByRole('button', { name: 'processingGateLoginSubmit' });
        expect(screen.queryByRole('link', { name: 'registerLegalTermsLink' }))
            .not.toBeInTheDocument();
        expect(screen.queryByRole('link', { name: 'registerLegalPrivacyLink' }))
            .not.toBeInTheDocument();
        expect(loginButton).not.toHaveAttribute('aria-describedby');
        fireEvent.click(loginButton);

        await waitFor(() => {
            expect(login).toHaveBeenCalledWith('creator@example.com', 'correct-password');
            expect(onAuthenticated).toHaveBeenCalledTimes(1);
        });
        expect(onConfirm).not.toHaveBeenCalled();
    });

    // REGRESSION: legal navigation replaced the upload workspace and lost the
    // guest's selected video and inline registration state.
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
        const legalNotice = document.getElementById('processing-gate-register-legal-notice');
        expect(legalNotice).toBeInTheDocument();
        expect(legalNotice).toHaveTextContent('registerLegalIntro');
        expect(legalNotice).toHaveTextContent('registerLegalConnector');
        const termsLink = screen.getByRole('link', { name: 'registerLegalTermsLink' });
        const privacyLink = screen.getByRole('link', { name: 'registerLegalPrivacyLink' });
        expect(termsLink).toHaveAttribute('href', '/terms');
        expect(termsLink).toHaveAttribute('target', '_blank');
        expect(termsLink).toHaveAttribute('rel', 'noopener noreferrer');
        expect(privacyLink).toHaveAttribute('href', '/privacy');
        expect(privacyLink).toHaveAttribute('target', '_blank');
        expect(privacyLink).toHaveAttribute('rel', 'noopener noreferrer');

        fireEvent.change(screen.getByLabelText('registerNameLabel'), { target: { value: 'Creator' } });
        fireEvent.change(screen.getByLabelText('loginEmailLabel'), { target: { value: 'new@example.com' } });
        fireEvent.change(screen.getByLabelText('loginPasswordLabel'), { target: { value: 'twelve-chars!' } });
        const registerButton = screen.getByRole('button', { name: 'processingGateRegisterSubmit' });
        expect(registerButton).toHaveAttribute(
            'aria-describedby',
            'processing-gate-register-legal-notice',
        );
        expect(legalNotice?.nextElementSibling).toBe(registerButton);
        fireEvent.click(registerButton);

        await waitFor(() => {
            expect(register).toHaveBeenCalledWith('new@example.com', 'twelve-chars!', 'Creator');
            expect(onAuthenticated).toHaveBeenCalledTimes(1);
        });
    });

    it('does not steal focus back from the password field after initial autofocus', () => {
        jest.useFakeTimers();
        render(
            <ProcessingGateModal
                isOpen
                stage="auth"
                cost={50}
                balance={null}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={onConfirm}
            />,
        );

        const emailInput = screen.getByLabelText('loginEmailLabel');
        const passwordInput = screen.getByLabelText('loginPasswordLabel');
        expect(emailInput).toHaveFocus();

        fireEvent.change(emailInput, { target: { value: 'guest@example.com' } });
        passwordInput.focus();
        act(() => jest.advanceTimersByTime(100));

        expect(passwordInput).toHaveFocus();
        fireEvent.change(passwordInput, { target: { value: 'correct horse battery staple' } });
        expect(emailInput).toHaveValue('guest@example.com');
        expect(passwordInput).toHaveValue('correct horse battery staple');
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

    it('labels mock processing as local and does not claim an external call', () => {
        render(
            <ProcessingGateModal
                isOpen
                stage="cost"
                cost={25}
                balance={100}
                requiresPaidCredits={false}
                isBalanceLoading={false}
                error=""
                onClose={onClose}
                onAuthenticated={onAuthenticated}
                onConfirm={onConfirm}
            />,
        );

        expect(screen.getByText('processingGateTotalBalanceLabel')).toBeInTheDocument();
        expect(screen.getByText('processingGateLocalChargeNote')).toBeInTheDocument();
        expect(screen.queryByText('processingGateBalanceLabel')).not.toBeInTheDocument();
        expect(screen.queryByText('processingGateChargeNote')).not.toBeInTheDocument();
    });

    it('routes an insufficient balance to credit purchase without starting processing', () => {
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
                onPurchaseCredits={onPurchaseCredits}
            />,
        );

        expect(screen.getByRole('alert')).toHaveTextContent('processingGateInsufficient');
        expect(screen.queryByRole('button', { name: 'processingGateConfirm' })).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'processingGateBuyCredits' }));
        expect(onPurchaseCredits).toHaveBeenCalledTimes(1);
        expect(onConfirm).not.toHaveBeenCalled();
    });

    // REGRESSION: a disabled paid-credit release still exposed a non-working
    // "buy credits" call to action from the processing gate.
    it('does not expose a purchase call to action without an approved callback', () => {
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
        expect(screen.queryByRole('button', {
            name: 'processingGateBuyCredits',
        })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {
            name: 'processingGateConfirm',
        })).not.toBeInTheDocument();
        expect(screen.getByRole('button', {
            name: 'processingGateCancel',
        })).toBeInTheDocument();
    });
});
