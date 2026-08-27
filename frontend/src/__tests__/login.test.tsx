import React from 'react';
import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import LoginPage from '@/app/login/page';
import { GoogleSignInControl } from '@/components/GoogleSignInControl';
import { api } from '@/lib/api';
import {
    loadGoogleIdentityScript,
    reloadGoogleIdentityPage,
    type GoogleCredentialResponse,
} from '@/lib/googleIdentity';
import { useAuth } from '@/context/AuthContext';
import { useRouter } from 'next/navigation';

let mockGoogleUnavailableMessage = 'loginGoogleUnavailable';

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
    useI18n: () => ({
        t: (key: string) => (
            key === 'loginGoogleUnavailable' ? mockGoogleUnavailableMessage : key
        ),
    }),
}));

jest.mock('@/lib/googleIdentity', () => ({
    loadGoogleIdentityScript: jest.fn(),
    reloadGoogleIdentityPage: jest.fn(),
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
        mockGoogleUnavailableMessage = 'loginGoogleUnavailable';
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

    afterEach(() => {
        jest.useRealTimers();
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

    it('keeps Messenger users out of the unsupported Google WebView flow', async () => {
        const userAgent = jest.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) '
            + 'AppleWebKit/605.1.15 Mobile/15E148 '
            + '[FBAN/MessengerForiOS;FBAV/520.0.0.0.0]',
        );
        const clipboardDescriptor = Object.getOwnPropertyDescriptor(
            window.navigator,
            'clipboard',
        );
        const writeText = jest.fn().mockResolvedValue(undefined);
        Object.defineProperty(window.navigator, 'clipboard', {
            configurable: true,
            value: { writeText },
        });

        try {
            render(<LoginPage />);

            const fallback = await screen.findByTestId('google-embedded-browser-fallback');
            expect(fallback).toHaveTextContent('loginGoogleEmbeddedTitle');
            expect(fallback).toHaveTextContent('loginGoogleEmbeddedBody');
            expect(api.getGoogleAuthNonce).not.toHaveBeenCalled();
            expect(loadGoogleIdentityScript).not.toHaveBeenCalled();
            expect(window.google?.accounts?.id?.initialize).not.toHaveBeenCalled();

            fireEvent.click(screen.getByRole('button', {
                name: 'loginGoogleEmbeddedCopy',
            }));
            await waitFor(() => {
                expect(writeText).toHaveBeenCalledWith('http://localhost/login');
                expect(screen.getByRole('status')).toHaveTextContent(
                    'loginGoogleEmbeddedCopied',
                );
            });
            expect(screen.getByPlaceholderText('loginEmailPlaceholder')).toBeVisible();
        } finally {
            userAgent.mockRestore();
            if (clipboardDescriptor) {
                Object.defineProperty(window.navigator, 'clipboard', clipboardDescriptor);
            } else {
                Reflect.deleteProperty(window.navigator, 'clipboard');
            }
        }
    });

    it('does not rotate the nonce when the stored locale hydrates', async () => {
        // REGRESSION: translating the availability fallback used to restart the
        // initialization effect and issue an overlapping nonce-cookie rotation.
        const view = render(<LoginPage />);

        await waitFor(() => expect(googleCallback).toBeDefined());
        mockGoogleUnavailableMessage = 'Google login not available';
        view.rerender(<LoginPage />);

        await act(async () => {
            await Promise.resolve();
        });
        expect(api.getGoogleAuthNonce).toHaveBeenCalledTimes(1);
        expect(window.google?.accounts?.id?.initialize).toHaveBeenCalledTimes(1);
    });

    it('aborts a pending nonce request when the login page unmounts', async () => {
        let requestedSignal: AbortSignal | undefined;
        (api.getGoogleAuthNonce as jest.Mock).mockImplementation((signal?: AbortSignal) => {
            requestedSignal = signal;
            return new Promise(() => undefined);
        });

        const view = render(<LoginPage />);
        await waitFor(() => expect(requestedSignal).toBeDefined());

        view.unmount();

        expect(requestedSignal?.aborted).toBe(true);
        expect(loadGoogleIdentityScript).not.toHaveBeenCalled();
    });

    it('expires the Google button from expires_in and never posts its stale credential', async () => {
        // REGRESSION: a login page left open past the nonce-cookie TTL used to
        // submit the old Google credential and surface a raw nonce error.
        jest.useFakeTimers();
        jest.setSystemTime(new Date('2026-08-20T12:00:00Z'));
        (api.getGoogleAuthNonce as jest.Mock).mockResolvedValue({
            nonce: 'short-lived-nonce',
            expires_in: 10,
            client_id: 'google-client-id',
        });

        render(<LoginPage />);

        await waitFor(() => expect(googleCallback).toBeDefined());
        const staleCallback = googleCallback;

        act(() => {
            jest.advanceTimersByTime(10_000);
        });

        expect(screen.getByRole('status')).toHaveTextContent('loginGoogleExpired');
        expect(screen.getByRole('button', { name: 'loginGoogleReload' })).toBeVisible();

        act(() => {
            staleCallback?.({ credential: 'expired-google-id-token' });
        });

        expect(mockGoogleLogin).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'loginGoogleReload' }));
        expect(reloadGoogleIdentityPage).toHaveBeenCalledTimes(1);
    });

    it('checks nonce expiry again when a throttled timer has not fired', async () => {
        jest.useFakeTimers();
        jest.setSystemTime(new Date('2026-08-20T12:00:00Z'));
        (api.getGoogleAuthNonce as jest.Mock).mockResolvedValue({
            nonce: 'short-lived-nonce',
            expires_in: 10,
            client_id: 'google-client-id',
        });

        render(<LoginPage />);

        await waitFor(() => expect(googleCallback).toBeDefined());
        jest.setSystemTime(new Date('2026-08-20T12:00:10Z'));

        act(() => {
            googleCallback?.({ credential: 'expired-google-id-token' });
        });

        expect(mockGoogleLogin).not.toHaveBeenCalled();
        expect(screen.getByRole('status')).toHaveTextContent('loginGoogleExpired');
    });

    it('does not initialize GIS when the nonce expires while its script is loading', async () => {
        jest.useFakeTimers();
        jest.setSystemTime(new Date('2026-08-20T12:00:00Z'));
        let finishScriptLoad: (() => void) | undefined;
        (loadGoogleIdentityScript as jest.Mock).mockReturnValue(new Promise<void>((resolve) => {
            finishScriptLoad = resolve;
        }));
        (api.getGoogleAuthNonce as jest.Mock).mockResolvedValue({
            nonce: 'short-lived-nonce',
            expires_in: 10,
            client_id: 'google-client-id',
        });

        render(<LoginPage />);

        await waitFor(() => expect(finishScriptLoad).toBeDefined());
        jest.setSystemTime(new Date('2026-08-20T12:00:10Z'));
        await act(async () => {
            finishScriptLoad?.();
            await Promise.resolve();
        });

        expect(window.google?.accounts?.id?.initialize).not.toHaveBeenCalled();
        expect(screen.getByRole('status')).toHaveTextContent('loginGoogleExpired');
    });

    it('fails closed when expires_in is not a positive lifetime', async () => {
        (api.getGoogleAuthNonce as jest.Mock).mockResolvedValue({
            nonce: 'invalid-lifetime-nonce',
            expires_in: 0,
            client_id: 'google-client-id',
        });

        render(<LoginPage />);

        await waitFor(() => {
            expect(screen.getByRole('status')).toHaveTextContent('loginGoogleUnavailable');
        });
        expect(loadGoogleIdentityScript).not.toHaveBeenCalled();
        expect(mockGoogleLogin).not.toHaveBeenCalled();
    });

    it('localizes a server nonce rejection and never retries the submitted credential', async () => {
        // REGRESSION: when the HttpOnly nonce cookie expired just before POST,
        // the backend detail was shown in English and the stale attempt could
        // remain attached to an apparently active Google button.
        mockGoogleLogin.mockRejectedValue(new Error('Google login nonce is required.'));
        render(<LoginPage />);

        await waitFor(() => expect(googleCallback).toBeDefined());
        const staleCallback = googleCallback;
        await act(async () => {
            staleCallback?.({ credential: 'stale-google-id-token' });
            await Promise.resolve();
        });

        await waitFor(() => {
            expect(screen.getByRole('status')).toHaveTextContent('loginGoogleExpired');
        });
        expect(screen.queryByText('Google login nonce is required.')).not.toBeInTheDocument();
        expect(mockGoogleLogin).toHaveBeenCalledTimes(1);

        act(() => {
            staleCallback?.({ credential: 'stale-google-id-token' });
        });
        expect(mockGoogleLogin).toHaveBeenCalledTimes(1);
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

    it('shows one localized availability notice when Google initialization fails', async () => {
        (api.getGoogleAuthNonce as jest.Mock).mockRejectedValue(
            new Error('Google auth unavailable'),
        );
        render(<LoginPage />);

        await waitFor(() => {
            expect(screen.getByRole('status')).toHaveTextContent('loginGoogleUnavailable');
        });
        expect(screen.queryByText('Google auth unavailable')).not.toBeInTheDocument();
        expect(document.querySelectorAll('.auth-error')).toHaveLength(0);
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

    it('reinitializes inline with a fresh nonce and leaves the stale callback inert', async () => {
        // REGRESSION: inline auth cannot reload the page because doing so discards
        // the guest's selected video and processing settings.
        (api.getGoogleAuthNonce as jest.Mock)
            .mockResolvedValueOnce({
                nonce: 'first-nonce',
                expires_in: 600,
                client_id: 'google-client-id',
            })
            .mockResolvedValueOnce({
                nonce: 'fresh-nonce',
                expires_in: 600,
                client_id: 'google-client-id',
            });
        const onAuthenticated = jest.fn();

        render(
            <GoogleSignInControl
                onAuthenticated={onAuthenticated}
                recoveryStrategy="reinitialize"
            />,
        );

        await waitFor(() => expect(googleCallback).toBeDefined());
        const staleCallback = googleCallback;
        mockGoogleLogin.mockRejectedValueOnce(
            new Error('Google login nonce could not be verified.'),
        );
        await act(async () => {
            staleCallback?.({ credential: 'stale-google-id-token' });
            await Promise.resolve();
        });

        await waitFor(() => {
            expect(screen.getByRole('status')).toHaveTextContent('loginGoogleExpired');
        });
        fireEvent.click(screen.getByRole('button', { name: 'loginGoogleReload' }));

        await waitFor(() => {
            expect(api.getGoogleAuthNonce).toHaveBeenCalledTimes(2);
            expect(window.google?.accounts?.id?.initialize).toHaveBeenLastCalledWith(
                expect.objectContaining({ nonce: 'fresh-nonce' }),
            );
        });
        expect(reloadGoogleIdentityPage).not.toHaveBeenCalled();

        act(() => {
            staleCallback?.({ credential: 'stale-google-id-token' });
        });
        expect(mockGoogleLogin).toHaveBeenCalledTimes(1);
        expect(onAuthenticated).not.toHaveBeenCalled();

        mockGoogleLogin.mockResolvedValueOnce(undefined);
        await act(async () => {
            googleCallback?.({ credential: 'fresh-google-id-token' });
            await Promise.resolve();
        });

        await waitFor(() => {
            expect(mockGoogleLogin).toHaveBeenLastCalledWith('fresh-google-id-token');
            expect(onAuthenticated).toHaveBeenCalledTimes(1);
        });
    });

    // REGRESSION: closing an inline auth surface while Google exchange was in
    // flight could let the stale continuation reopen the next modal stage.
    it('does not continue authentication after the Google control unmounts', async () => {
        let resolveGoogleLogin: (() => void) | undefined;
        mockGoogleLogin.mockReturnValue(new Promise<void>((resolve) => {
            resolveGoogleLogin = resolve;
        }));
        const onAuthenticated = jest.fn();
        const view = render(
            <GoogleSignInControl
                onAuthenticated={onAuthenticated}
                recoveryStrategy="reinitialize"
            />,
        );

        await waitFor(() => expect(googleCallback).toBeDefined());
        act(() => {
            googleCallback?.({ credential: 'in-flight-google-id-token' });
        });
        await waitFor(() => {
            expect(mockGoogleLogin).toHaveBeenCalledWith('in-flight-google-id-token');
        });

        view.unmount();
        await act(async () => {
            resolveGoogleLogin?.();
            await Promise.resolve();
        });

        expect(onAuthenticated).not.toHaveBeenCalled();
    });
});
