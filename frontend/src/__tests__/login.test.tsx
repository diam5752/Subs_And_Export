import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import LoginPage from '@/app/login/page';
import { api } from '@/lib/api';
import {
    loadGoogleIdentityScript,
    type GoogleCredentialResponse,
} from '@/lib/googleIdentity';
import { useAuth } from '@/context/AuthContext';
import { useRouter } from 'next/navigation';

jest.mock('@/lib/api', () => ({
    api: {
        login: jest.fn(),
        register: jest.fn(),
        googleLogin: jest.fn(),
        getGoogleAuthNonce: jest.fn(),
        getCurrentUser: jest.fn(),
    },
}));

jest.mock('@/context/AuthContext', () => ({
    useAuth: jest.fn(),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('@/lib/googleIdentity', () => ({
    loadGoogleIdentityScript: jest.fn(),
}));

jest.mock('next/navigation', () => ({
    useRouter: jest.fn(),
}));

describe('LoginPage', () => {
    const mockLogin = jest.fn();
    const mockGoogleLogin = jest.fn();
    const mockPush = jest.fn();
    let googleCallback: ((response: GoogleCredentialResponse) => void) | undefined;
    beforeEach(() => {
        jest.clearAllMocks();
        localStorage.clear();
        (useAuth as jest.Mock).mockReturnValue({
            login: mockLogin,
            googleLogin: mockGoogleLogin,
            user: null,
            isLoading: false,
        });
        (useRouter as jest.Mock).mockReturnValue({ push: mockPush });
        (api.getCurrentUser as jest.Mock).mockResolvedValue({ id: '1', name: 'Test' });
        (api.getGoogleAuthNonce as jest.Mock).mockResolvedValue({
            nonce: 'nonce-123',
            expires_in: 600,
            client_id: 'google-client-id',
        });
        (loadGoogleIdentityScript as jest.Mock).mockResolvedValue(undefined);
        googleCallback = undefined;
        window.google = {
            accounts: {
                id: {
                    initialize: jest.fn((options) => {
                        googleCallback = options.callback;
                    }),
                    renderButton: jest.fn((parent) => {
                        const button = document.createElement('button');
                        button.textContent = 'official-google-button';
                        parent.appendChild(button);
                    }),
                },
            },
        };
    });

    it('renders login form by default', () => {
        render(<LoginPage />);
        const homeLink = screen.getByRole('link', { name: 'brandHomeLabel' });
        expect(within(homeLink).getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-logo.svg');
        expect(screen.getByText('gsubs')).toBeInTheDocument();
        expect(screen.getByText('loginHeading')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('loginEmailPlaceholder')).toBeInTheDocument();
        expect(screen.queryByText(/Mock|€0/)).not.toBeInTheDocument();
    });

    it('has link to register page', () => {
        render(<LoginPage />);
        const link = screen.getByText('loginCreateOne');
        expect(link).toBeInTheDocument();
        expect(link.closest('a')).toHaveAttribute('href', '/register');
    });

    it('handles email/password login', async () => {
        render(<LoginPage />);

        fireEvent.change(screen.getByPlaceholderText('loginEmailPlaceholder'), {
            target: { value: 'test@test.com' },
        });
        fireEvent.change(screen.getByPlaceholderText('loginPasswordPlaceholder'), {
            target: { value: 'password' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'loginSubmit' }));

        await waitFor(() => {
            expect(mockLogin).toHaveBeenCalledWith('test@test.com', 'password');
        });
    });

    it('handles login error', async () => {
        mockLogin.mockRejectedValue(new Error('Invalid credentials'));
        render(<LoginPage />);

        fireEvent.change(screen.getByPlaceholderText('loginEmailPlaceholder'), {
            target: { value: 'test@test.com' },
        });
        fireEvent.change(screen.getByPlaceholderText('loginPasswordPlaceholder'), {
            target: { value: 'wrong' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'loginSubmit' }));

        await waitFor(() => {
            expect(screen.getByText('Invalid credentials')).toBeInTheDocument();
        });
    });

    it('initializes the official Google button with a server nonce', async () => {
        render(<LoginPage />);

        await waitFor(() => {
            expect(api.getGoogleAuthNonce).toHaveBeenCalled();
            expect(loadGoogleIdentityScript).toHaveBeenCalled();
            expect(window.google?.accounts?.id?.initialize).toHaveBeenCalledWith(
                expect.objectContaining({
                    client_id: 'google-client-id',
                    nonce: 'nonce-123',
                    ux_mode: 'popup',
                    callback: expect.any(Function),
                }),
            );
            expect(window.google?.accounts?.id?.renderButton).toHaveBeenCalledWith(
                expect.any(HTMLElement),
                expect.objectContaining({
                    type: 'standard',
                    size: 'large',
                    text: 'signin_with',
                    locale: 'el',
                }),
            );
            expect(screen.getByText('official-google-button')).toBeInTheDocument();
        });
    });

    it('exchanges the Google credential and opens the app', async () => {
        mockGoogleLogin.mockResolvedValue(undefined);
        render(<LoginPage />);

        await waitFor(() => expect(googleCallback).toBeDefined());
        googleCallback?.({ credential: 'signed-google-id-token' });

        await waitFor(() => {
            expect(mockGoogleLogin).toHaveBeenCalledWith('signed-google-id-token');
            expect(mockPush).toHaveBeenCalledWith('/');
        });
    });

    it('shows a safe error when Google initialization fails', async () => {
        (api.getGoogleAuthNonce as jest.Mock).mockRejectedValue(
            new Error('Google auth unavailable'),
        );
        render(<LoginPage />);

        await waitFor(() => {
            expect(screen.getByText('Google auth unavailable')).toBeInTheDocument();
        });
    });

    it('shows a safe error when the credential exchange fails', async () => {
        mockGoogleLogin.mockRejectedValue(new Error('OAuth failed'));
        render(<LoginPage />);

        await waitFor(() => expect(googleCallback).toBeDefined());
        googleCallback?.({ credential: 'signed-google-id-token' });

        await waitFor(() => {
            expect(screen.getByText('OAuth failed')).toBeInTheDocument();
        });
    });

    it('fails closed when the backend omits the Google client ID', async () => {
        (api.getGoogleAuthNonce as jest.Mock).mockResolvedValue({
            nonce: 'nonce-123',
            expires_in: 600,
            client_id: '',
        });

        render(<LoginPage />);

        await waitFor(() => {
            expect(screen.getByText('loginGoogleUnavailable')).toBeInTheDocument();
        });
    });
});
