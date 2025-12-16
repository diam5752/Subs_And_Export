import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardPage from '@/app/page';
import LoginPage from '@/app/login/page';
import { LanguageToggle } from '@/components/LanguageToggle';
import { I18nProvider, useI18n } from '@/context/I18nContext';
import { messages } from '@/context/i18nMessages';

jest.mock('@/context/AuthContext', () => {
    const loginMock = jest.fn();
    const googleLoginMock = jest.fn();
    const logoutMock = jest.fn();
    const refreshUserMock = jest.fn();
    return {
        useAuth: () => ({
            login: loginMock,
            googleLogin: googleLoginMock,
            logout: logoutMock,
            refreshUser: refreshUserMock,
            user: { id: '1', name: 'Tester', email: 't@e.com', provider: 'google' },
            isLoading: false,
        }),
        __loginMock: loginMock,
        __googleLoginMock: googleLoginMock,
        __logoutMock: logoutMock,
        __refreshUserMock: refreshUserMock,
    };
});

jest.mock('next/navigation', () => ({
    useRouter: () => ({ push: jest.fn() }),
    useSearchParams: () => ({
        get: () => null,
    }),
}));

jest.mock('@/lib/api', () => {
    const actual = jest.requireActual('@/lib/api');
    const getJobs = jest.fn();
    const getHistory = jest.fn();
    return {
        ...actual,
        API_BASE: 'http://localhost:8000',
        api: {
            ...actual.api,
            getJobs,
            getHistory,
            processVideo: jest.fn(),
            getJobStatus: jest.fn(),
        },
        __getJobsMock: getJobs,
        __getHistoryMock: getHistory,
    };
});

const { __getJobsMock, __getHistoryMock } = jest.requireMock('@/lib/api');
const getJobsMock = __getJobsMock as jest.Mock;
const getHistoryMock = __getHistoryMock as jest.Mock;

const renderWithI18n = (ui: React.ReactNode, initialLocale?: 'el' | 'en') =>
    render(<I18nProvider initialLocale={initialLocale}>{ui}</I18nProvider>);

const TranslatedProbe = () => {
    const { t } = useI18n();
    return (
        <div>
            <p data-testid="hero-copy">{t('heroTitle')}</p>
            <LanguageToggle />
        </div>
    );
};

beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    getJobsMock.mockResolvedValue([]);
    getHistoryMock.mockResolvedValue([]);
});

afterEach(() => {
    jest.useRealTimers();
});

describe('i18n provider defaults and persistence', () => {
    it('renders Greek copy by default and updates <html lang> accordingly', async () => {
        renderWithI18n(<LoginPage />);

        expect(await screen.findByText('Συνδεθείτε στον λογαριασμό σας')).toBeInTheDocument();
        await waitFor(() => expect(document.documentElement.lang).toBe('el'));
    });

    it('switches to English through the toggle and persists the locale', async () => {
        renderWithI18n(<TranslatedProbe />);

        expect(screen.getByTestId('hero-copy')).toHaveTextContent(messages.el.heroTitle);
        expect(document.documentElement.lang).toBe('el');

        // Updated: LanguageToggle now shows flag with "Switch to" aria-label
        const toggle = screen.getByRole('button', { name: /Switch to English/i });
        fireEvent.click(toggle);

        await waitFor(() => {
            expect(document.documentElement.lang).toBe('en');
            expect(localStorage.getItem('preferredLocale')).toBe('en');
            expect(screen.getByTestId('hero-copy')).toHaveTextContent(messages.en.heroTitle);
        });
    });

    it('rehydrates from persisted English preference on load', async () => {
        localStorage.setItem('preferredLocale', 'en');

        renderWithI18n(<TranslatedProbe />);

        await waitFor(() => expect(document.documentElement.lang).toBe('en'));
        const toggle = screen.getByRole('button', { name: /Switch to/i });
        expect(toggle).toBeInTheDocument();
    });
});

describe('localized pages', () => {
    it('shows Greek strings across dashboard by default', async () => {
        renderWithI18n(<DashboardPage />);

        // Check for Greek hero title text instead of removed tabs
        expect(await screen.findByText(/Φτιάξτε shorts έτοιμα/i)).toBeInTheDocument();

        // Select a model to show upload section
        fireEvent.click(screen.getByTestId('model-whispercpp'));

        expect(screen.getByText('Ρίξτε το κάθετο κλιπ σας')).toBeInTheDocument();
    });

    it('renders English copy when locale is set to en', async () => {
        // Mock scrollIntoView for this test to avoid JSDOM errors
        const originalScrollIntoView = Element.prototype.scrollIntoView;
        Element.prototype.scrollIntoView = jest.fn();

        try {
            renderWithI18n(
                <div>
                    <DashboardPage />
                    <LoginPage />
                </div>,
                'en',
            );

            // Check for English hero and UI elements instead of removed 'Workspace' tab
            expect(await screen.findByText(/Build export-ready shorts/i)).toBeInTheDocument();

            // Select a model to show upload section
            fireEvent.click(screen.getByTestId('model-whispercpp'));

            expect(screen.getByText('Drop your vertical clip')).toBeInTheDocument();
            expect(screen.getByText('Sign in to your account')).toBeInTheDocument();
        } finally {
            Element.prototype.scrollIntoView = originalScrollIntoView;
        }
    });

    it('throws error when useI18n is used outside of I18nProvider', () => {
        // Prevent console.error from cluttering the test output
        const consoleError = jest.spyOn(console, 'error').mockImplementation(() => { });

        const BadComponent = () => {
            useI18n();
            return null;
        };

        expect(() => render(<BadComponent />)).toThrow('useI18n must be used within an I18nProvider');

        consoleError.mockRestore();
    });
});
