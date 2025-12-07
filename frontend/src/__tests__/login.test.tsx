/**
 * Regression tests for the login page, including Google OAuth handoff.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import LoginPage from '@/app/login/page';
import { I18nProvider } from '@/context/I18nContext';

const searchParamsState: { code: string | null; state: string | null } = {
    code: null,
    state: null,
};

jest.mock('@/context/AuthContext', () => {
    const loginMock = jest.fn();
    const googleLoginMock = jest.fn();
    return {
        useAuth: () => ({
            login: loginMock,
            googleLogin: googleLoginMock,
        }),
        __loginMock: loginMock,
        __googleLoginMock: googleLoginMock,
    };
});

jest.mock('next/navigation', () => ({
    useRouter: () => ({ push: jest.fn() }),
    useSearchParams: () => ({
        get: (key: string) => {
            if (key === 'code') return searchParamsState.code;
            if (key === 'state') return searchParamsState.state;
            return null;
        },
    }),
}));

jest.mock('@/lib/api', () => {
    const actual = jest.requireActual('@/lib/api');
    const getGoogleAuthUrl = jest.fn();
    return {
        ...actual,
        api: {
            ...actual.api,
            getGoogleAuthUrl,
        },
        __getGoogleAuthUrlMock: getGoogleAuthUrl,
    };
});

// Pull mocks after factories are evaluated
const { __loginMock, __googleLoginMock } = jest.requireMock('@/context/AuthContext');
const { __getGoogleAuthUrlMock } = jest.requireMock('@/lib/api');
const loginMock = __loginMock as jest.Mock;
const googleLoginMock = __googleLoginMock as jest.Mock;
const getGoogleAuthUrlMock = __getGoogleAuthUrlMock as jest.Mock;

const renderLogin = () => render(
    <I18nProvider initialLocale="en">
        <LoginPage />
    </I18nProvider>
);

beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    searchParamsState.code = null;
    searchParamsState.state = null;
    loginMock.mockResolvedValue(undefined);
    googleLoginMock.mockResolvedValue(undefined);
    getGoogleAuthUrlMock.mockReset();
});

it('invokes Google login when callback params match stored state', async () => {
    searchParamsState.code = 'abc';
    searchParamsState.state = 'state123';
    localStorage.setItem('google_oauth_state', 'state123');

    renderLogin();

    await waitFor(() => {
        expect(googleLoginMock).toHaveBeenCalledWith('abc', 'state123');
    });
    expect(localStorage.getItem('google_oauth_state')).toBeNull();
});

it('requests Google auth URL and redirects when button is clicked', async () => {
    getGoogleAuthUrlMock.mockResolvedValueOnce({
        auth_url: 'http://auth.example.com',
        state: 'generated_state',
    });

    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

    renderLogin();

    const btn = screen.getByRole('button', { name: /Continue with Google/i });
    fireEvent.click(btn);

    await waitFor(() => expect(getGoogleAuthUrlMock).toHaveBeenCalled());
    expect(localStorage.getItem('google_oauth_state')).toBe('generated_state');
    consoleSpy.mockRestore();
});

it('submits email/password through the login handler', async () => {
    renderLogin();

    fireEvent.change(screen.getByLabelText(/Email Address/i), { target: { value: 'you@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: 'hunter2' } });

    fireEvent.click(screen.getByRole('button', { name: /Sign In/i }));

    await waitFor(() => {
        expect(loginMock).toHaveBeenCalledWith('you@example.com', 'hunter2');
    });
});
