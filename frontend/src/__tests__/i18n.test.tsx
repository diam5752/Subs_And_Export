import React from 'react';
import fs from 'fs';
import path from 'path';
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

jest.mock('@/context/PointsContext', () => ({
    usePoints: () => ({
        balance: 1000,
        isLoading: false,
        error: null,
        refreshBalance: jest.fn(),
        setBalance: jest.fn(),
    }),
}));

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
        API_BASE: 'http://localhost:8080',
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

function collectTranslationKeysUsedInSource() {
    const srcRoot = path.join(process.cwd(), 'src');
    const usedKeys = new Set<string>();

    const walk = (dir: string) => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const fullPath = path.join(dir, entry.name);
            if (entry.isDirectory()) {
                if (entry.name === '__tests__') continue;
                walk(fullPath);
                continue;
            }
            if (!/\.(ts|tsx|js|jsx)$/.test(entry.name)) continue;

            const text = fs.readFileSync(fullPath, 'utf8');
            const matches = text.matchAll(/\bt\(\s*['"]([^'"]+)['"]/g);
            for (const match of matches) {
                usedKeys.add(match[1]);
            }
        }
    };

    walk(srcRoot);
    return [...usedKeys].sort();
}

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
    it('keeps locale dictionaries in sync for model-selection labels', () => {
        /**
         * REGRESSION: `ModelSelector` uses `t("modelInfo")`, so missing locale keys
         * break the production TypeScript build even if the dev server appears healthy.
         */
        expect(Object.keys(messages.el).sort()).toEqual(Object.keys(messages.en).sort());
        expect(messages.el.modelInfo).toBe('Πληροφορίες σύγκρισης μοντέλων');
        expect(messages.en.modelInfo).toBe('Model comparison information');
    });

    it('covers every translation key used by production source files', () => {
        /**
         * REGRESSION: several `t("...")` calls were missing from both locale files,
         * which only surfaced during the production Next.js build.
         */
        const usedKeys = collectTranslationKeysUsedInSource();
        const missingFromEnglish = usedKeys.filter((key) => !(key in messages.en));
        const missingFromGreek = usedKeys.filter((key) => !(key in messages.el));

        expect(missingFromEnglish).toEqual([]);
        expect(missingFromGreek).toEqual([]);
    });

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
        const toggle = screen.getByRole('button', { name: /Αλλαγή σε Αγγλικά/i });
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
        fireEvent.click(screen.getByTestId('model-standard'));

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
            fireEvent.click(screen.getByTestId('model-standard'));

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
