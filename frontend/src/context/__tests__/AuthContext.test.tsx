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
        googleLogin: jest.fn(),
        revokeSession: jest.fn(),
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
            <button type="button" onClick={() => void googleLogin('signed-google-id-token')}>
                google
            </button>
            <button type="button" onClick={() => void logout().catch(() => undefined)}>
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
        localStorage.clear();
        localStorage.setItem('auth_token', 'test-token');
        (api.getCurrentUser as jest.Mock).mockResolvedValue({
            id: 'u1',
            email: 'user@example.com',
            name: 'User',
            provider: 'local',
        });
        (api.revokeSession as jest.Mock).mockResolvedValue({
            status: 'success',
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

    it('skips the session lookup when no token is stored', async () => {
        localStorage.clear();

        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => {
            expect(api.getCurrentUser).not.toHaveBeenCalled();
            expect(screen.getByTestId('user-email')).toHaveTextContent('none');
            expect(screen.getByTestId('loading')).toHaveTextContent('false');
        });
    });

    it('revokes the media cookie before clearing a rejected initial session', async () => {
        (api.getCurrentUser as jest.Mock).mockRejectedValueOnce({ status: 401 });

        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => {
            expect(api.revokeSession).toHaveBeenCalledTimes(1);
            expect(api.clearToken).toHaveBeenCalled();
            expect(screen.getByTestId('user-email')).toHaveTextContent('none');
            expect(screen.getByTestId('loading')).toHaveTextContent('false');
        });
    });

    it('does not falsely sign out while the initial session check is transiently unavailable', async () => {
        (api.getCurrentUser as jest.Mock).mockRejectedValueOnce({ status: 503 });

        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(api.getCurrentUser).toHaveBeenCalledTimes(1));
        expect(api.revokeSession).not.toHaveBeenCalled();
        expect(api.clearToken).not.toHaveBeenCalled();
        expect(localStorage.getItem('auth_token')).toBe('test-token');
        expect(screen.getByTestId('loading')).toHaveTextContent('true');
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
            expect(api.googleLogin).toHaveBeenCalledWith('signed-google-id-token');
            expect(api.getCurrentUser).toHaveBeenCalledTimes(2);
        });
    });

    it('clears local private state only after server revocation succeeds', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com'));

        fireEvent.click(screen.getByRole('button', { name: 'logout' }));

        await waitFor(() => {
            expect(api.revokeSession).toHaveBeenCalledTimes(1);
            expect(api.clearToken).toHaveBeenCalled();
            expect(screen.getByTestId('user-email')).toHaveTextContent('none');
        });
        expect((api.revokeSession as jest.Mock).mock.invocationCallOrder[0])
            .toBeLessThan((api.clearToken as jest.Mock).mock.invocationCallOrder[0]);
    });

    it('keeps the user visibly signed in when server revocation fails', async () => {
        (api.revokeSession as jest.Mock).mockRejectedValueOnce(
            new Error('network unavailable'),
        );
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com'));

        fireEvent.click(screen.getByRole('button', { name: 'logout' }));

        await waitFor(() => expect(api.revokeSession).toHaveBeenCalledTimes(1));
        expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com');
        expect(api.clearToken).not.toHaveBeenCalled();
    });

    it('clears the token when refreshUser receives a definitive rejection', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com'));

        (api.getCurrentUser as jest.Mock).mockRejectedValueOnce({ status: 401 });
        fireEvent.click(screen.getByRole('button', { name: 'refresh' }));

        await waitFor(() => {
            expect(api.revokeSession).toHaveBeenCalledTimes(1);
            expect(api.clearToken).toHaveBeenCalled();
            expect(screen.getByTestId('user-email')).toHaveTextContent('none');
        });
    });

    it('preserves an established session on refresh network and server errors', async () => {
        render(
            <AuthProvider>
                <AuthHarness />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com'));

        (api.getCurrentUser as jest.Mock).mockRejectedValueOnce(new Error('network unavailable'));
        fireEvent.click(screen.getByRole('button', { name: 'refresh' }));

        await waitFor(() => expect(api.getCurrentUser).toHaveBeenCalledTimes(2));
        expect(api.revokeSession).not.toHaveBeenCalled();
        expect(api.clearToken).not.toHaveBeenCalled();
        expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com');
        expect(localStorage.getItem('auth_token')).toBe('test-token');
    });

    it('throws when useAuth is called outside a provider', () => {
        expect(() => render(<AuthHarness />)).toThrow('useAuth must be used within an AuthProvider');
    });
});
