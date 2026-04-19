import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { AuthProvider, useAuth } from '@/context/AuthContext';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
    api: {
        getCurrentUser: jest.fn(),
        clearToken: jest.fn(),
        login: jest.fn(),
        register: jest.fn(),
        googleCallback: jest.fn(),
    },
}));

function AuthHarness() {
    const { user, isLoading, login, register, googleLogin, logout, refreshUser } = useAuth();

    return (
        <div>
            <div data-testid="user-email">{user?.email ?? 'none'}</div>
            <div data-testid="loading">{String(isLoading)}</div>
            <button type="button" onClick={() => void login('user@example.com', 'secret')}>
                login
            </button>
            <button type="button" onClick={() => void register('new@example.com', 'secret', 'New User')}>
                register
            </button>
            <button type="button" onClick={() => void googleLogin('oauth-code', 'oauth-state')}>
                google
            </button>
            <button type="button" onClick={() => logout()}>
                logout
            </button>
            <button type="button" onClick={() => void refreshUser()}>
                refresh
            </button>
        </div>
    );
}

describe('AuthContext', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        (api.getCurrentUser as jest.Mock).mockResolvedValue({
            id: 'u1',
            email: 'user@example.com',
            name: 'User',
            provider: 'local',
        });
    });

    it('hydrates the active session on mount', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        expect(screen.getByTestId('loading')).toHaveTextContent('true');

        await waitFor(() => {
            expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com');
            expect(screen.getByTestId('loading')).toHaveTextContent('false');
        });
    });

    it('clears the token when the initial session lookup fails', async () => {
        (api.getCurrentUser as jest.Mock).mockRejectedValueOnce(new Error('no session'));

        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => {
            expect(api.clearToken).toHaveBeenCalled();
            expect(screen.getByTestId('user-email')).toHaveTextContent('none');
            expect(screen.getByTestId('loading')).toHaveTextContent('false');
        });
    });

    it('logs in and refreshes the user profile', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com'));

        fireEvent.click(screen.getByRole('button', { name: 'login' }));

        await waitFor(() => {
            expect(api.login).toHaveBeenCalledWith('user@example.com', 'secret');
            expect(api.getCurrentUser).toHaveBeenCalledTimes(2);
        });
    });

    it('registers and then logs the new user in', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));

        fireEvent.click(screen.getByRole('button', { name: 'register' }));

        await waitFor(() => {
            expect(api.register).toHaveBeenCalledWith('new@example.com', 'secret', 'New User');
            expect(api.login).toHaveBeenCalledWith('new@example.com', 'secret');
        });
    });

    it('handles Google login and refreshes the session', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));

        fireEvent.click(screen.getByRole('button', { name: 'google' }));

        await waitFor(() => {
            expect(api.googleCallback).toHaveBeenCalledWith('oauth-code', 'oauth-state');
            expect(api.getCurrentUser).toHaveBeenCalledTimes(2);
        });
    });

    it('clears the current user on logout', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com'));

        fireEvent.click(screen.getByRole('button', { name: 'logout' }));

        expect(api.clearToken).toHaveBeenCalled();
        expect(screen.getByTestId('user-email')).toHaveTextContent('none');
    });

    it('clears the token when refreshUser fails', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com'));

        (api.getCurrentUser as jest.Mock).mockRejectedValueOnce(new Error('expired'));
        fireEvent.click(screen.getByRole('button', { name: 'refresh' }));

        await waitFor(() => {
            expect(api.clearToken).toHaveBeenCalled();
            expect(screen.getByTestId('user-email')).toHaveTextContent('none');
        });
    });

    it('throws when useAuth is called outside a provider', () => {
        expect(() => render(<AuthHarness />)).toThrow('useAuth must be used within an AuthProvider');
    });
});
