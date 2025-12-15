
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import LoginPage from '@/app/login/page';
import { api } from '@/lib/api';
import { redirectTo } from '@/lib/navigation';
import { useAuth } from '@/context/AuthContext';
import { useRouter, useSearchParams } from 'next/navigation';

// Mocks
jest.mock('@/lib/api', () => ({
    api: {
        login: jest.fn(),
        register: jest.fn(),
        googleLogin: jest.fn(),
        getGoogleAuthUrl: jest.fn(),
        getCurrentUser: jest.fn(),
    },
}));

jest.mock('@/context/AuthContext', () => ({
    useAuth: jest.fn(),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('@/lib/navigation', () => ({
    redirectTo: jest.fn(),
}));

jest.mock('next/navigation', () => ({
    useRouter: jest.fn(),
    useSearchParams: jest.fn(),
}));

describe('LoginPage', () => {
    const mockLogin = jest.fn();
    const mockGoogleLogin = jest.fn();
    const mockPush = jest.fn();
    const mockSearchParamsGet = jest.fn();

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
        (useSearchParams as jest.Mock).mockReturnValue({ get: mockSearchParamsGet });
        (api.getCurrentUser as jest.Mock).mockResolvedValue({ id: '1', name: 'Test' });
        (api.getGoogleAuthUrl as jest.Mock).mockResolvedValue({ auth_url: 'http://foo.com', state: 'xyz' });
        mockSearchParamsGet.mockReturnValue(null);
    });

    it('renders login form by default', () => {
        render(<LoginPage />);
        expect(screen.getByText('loginHeading')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('loginEmailPlaceholder')).toBeInTheDocument();
    });

    it('has link to register page', () => {
        render(<LoginPage />);
        const link = screen.getByText('loginCreateOne');
        expect(link).toBeInTheDocument();
        expect(link.closest('a')).toHaveAttribute('href', '/register');
    });

    it('handles email/password login', async () => {
        render(<LoginPage />);

        fireEvent.change(screen.getByPlaceholderText('loginEmailPlaceholder'), { target: { value: 'test@test.com' } });
        fireEvent.change(screen.getByPlaceholderText('loginPasswordPlaceholder'), { target: { value: 'password' } });

        fireEvent.click(screen.getByRole('button', { name: 'loginSubmit' }));

        await waitFor(() => {
            expect(mockLogin).toHaveBeenCalledWith('test@test.com', 'password');
        });
    });

    it('handles login error', async () => {
        mockLogin.mockRejectedValue(new Error('Invalid credentials'));
        render(<LoginPage />);

        fireEvent.change(screen.getByPlaceholderText('loginEmailPlaceholder'), { target: { value: 'test@test.com' } });
        fireEvent.change(screen.getByPlaceholderText('loginPasswordPlaceholder'), { target: { value: 'wrong' } });
        fireEvent.click(screen.getByRole('button', { name: 'loginSubmit' }));

        await waitFor(() => {
            expect(screen.getByText('Invalid credentials')).toBeInTheDocument();
        });
    });

    it('handles google login start', async () => {
        render(<LoginPage />);
        fireEvent.click(screen.getByText('loginGoogleCta'));

        await waitFor(() => {
            expect(api.getGoogleAuthUrl).toHaveBeenCalled();
            expect(redirectTo).toHaveBeenCalledWith('http://foo.com');
            expect(screen.getByText('loginGoogleSigningIn')).toBeInTheDocument();
        });
    });

    it('handles google login error', async () => {
        (api.getGoogleAuthUrl as jest.Mock).mockRejectedValue(new Error('Google auth unavailable'));
        render(<LoginPage />);

        fireEvent.click(screen.getByText('loginGoogleCta'));

        await waitFor(() => {
            expect(screen.getByText('Google auth unavailable')).toBeInTheDocument();
        });
    });

    it('handles OAuth callback success', async () => {
        localStorage.setItem('google_oauth_state', 'test-state');
        mockSearchParamsGet.mockImplementation((key: string) => {
            if (key === 'code') return 'auth-code';
            if (key === 'state') return 'test-state';
            return null;
        });
        mockGoogleLogin.mockResolvedValue({ id: '1', name: 'Test' });

        render(<LoginPage />);

        await waitFor(() => {
            expect(mockGoogleLogin).toHaveBeenCalledWith('auth-code', 'test-state');
            expect(mockPush).toHaveBeenCalledWith('/');
        });
    });

    it('handles OAuth callback error', async () => {
        localStorage.setItem('google_oauth_state', 'test-state');
        mockSearchParamsGet.mockImplementation((key: string) => {
            if (key === 'code') return 'auth-code';
            if (key === 'state') return 'test-state';
            return null;
        });
        mockGoogleLogin.mockRejectedValue(new Error('OAuth failed'));

        render(<LoginPage />);

        await waitFor(() => {
            expect(screen.getByText('OAuth failed')).toBeInTheDocument();
        });
    });
});
