import React from 'react';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardPage from '@/app/page';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { useJobs } from '@/hooks/useJobs';

const mockPaidCreditLegalPublication = { approved: false };

// Mocks
jest.mock('@/lib/api', () => ({
    api: {
        getJobs: jest.fn(),
        getHistory: jest.fn(),
        getJobStatus: jest.fn(),
        processVideo: jest.fn(),
        reprocessJob: jest.fn(),
        cancelJob: jest.fn(),
        getPointsBalance: jest.fn(),
        getCreditCatalog: jest.fn(),
        createCreditCheckout: jest.fn(),
        getCreditCheckoutStatus: jest.fn(),
        updateProfile: jest.fn(),
        updatePassword: jest.fn(),
    },
}));

jest.mock('@/context/AuthContext', () => ({
    useAuth: jest.fn(),
}));

jest.mock('@/context/PointsContext', () => ({
    __esModule: true,
    ...(() => {
        const setBalanceMock = jest.fn();
        const setWalletMock = jest.fn();
        const refreshBalanceMock = jest.fn();
        const defaultPointsState = {
            balance: 125,
            paidBalance: 125,
            promotionalBalance: 0,
            reversalDebt: 0,
            aiSpendableBalance: 125,
        };
        const pointsState = { ...defaultPointsState };
        return {
            usePoints: () => ({
                ...pointsState,
                isLoading: false,
                error: null,
                setBalance: setBalanceMock,
                setWallet: setWalletMock,
                refreshBalance: refreshBalanceMock,
            }),
            __setBalanceMock: setBalanceMock,
            __setWalletMock: setWalletMock,
            __refreshBalanceMock: refreshBalanceMock,
            __setPointsStateMock: (nextState: Partial<typeof defaultPointsState>) => {
                Object.assign(pointsState, nextState);
            },
            __resetPointsStateMock: () => {
                Object.assign(pointsState, defaultPointsState);
            },
        };
    })(),
}));

jest.mock('@/context/I18nContext', () => {
    const translate = (key: string) => key;
    return {
        useI18n: () => ({ t: translate }),
    };
});

jest.mock('@/lib/paidCreditLegal', () => ({
    paidCreditLegalPublicationIsApproved: () => (
        mockPaidCreditLegalPublication.approved
    ),
}));

jest.mock('@/hooks/useJobs', () => ({
    useJobs: jest.fn(),
}));

let capturedPollingCallbacks: { onProgress: (progress: number, message: string) => void; onComplete: (job: unknown) => void; onFailed: (error: string) => void; onError: (error: string) => void; } | null = null;
let capturedPollingJobId: string | null = null;

jest.mock('@/hooks/useJobPolling', () => ({
    useJobPolling: ({ jobId, callbacks }: { jobId: string | null; callbacks: typeof capturedPollingCallbacks }) => {
        capturedPollingJobId = jobId;
        capturedPollingCallbacks = callbacks;
        return { isPolling: false, stopPolling: jest.fn() };
    },
}));

let capturedOnReset: (() => void) | null = null;

jest.mock('@/features/process/ProcessView', () => ({
    ProcessView: ({
        onStartProcessing,
        onFileSelect,
        onReset,
        onReprocessJob,
        isProcessing,
        progress,
        statusMessage,
        error,
        onCancelProcessing,
    }: {
        onStartProcessing: (options: unknown) => void;
        onFileSelect: (file: File) => void;
        onReset: () => void;
        onReprocessJob: (jobId: string, options: unknown) => void;
        isProcessing: boolean;
        progress: number;
        statusMessage: string;
        error: string;
        onCancelProcessing?: () => void;
    }) => {
        capturedOnReset = onReset;
        return (
            <div data-testid="process-view">
                <div data-testid="process-processing">{String(isProcessing)}</div>
                <div data-testid="process-progress">{progress}</div>
                <div data-testid="process-status">{statusMessage}</div>
                <div data-testid="process-error">{error}</div>
                <button onClick={() => onFileSelect(new File(['dummy'], 'test.mp4', { type: 'video/mp4' }))}>Select File</button>
                <button onClick={() => onStartProcessing({
                    transcribeMode: 'standard',
                    transcribeProvider: 'mock',
                    outputQuality: 'balanced',
                    outputResolution: '1080x1920',
                    width: 1920,
                    height: 1080,
                    duration: 10,
                    sourceDurationSeconds: 10,
                    subtitle_position: 16,
                    max_subtitle_lines: 2,
                    watermark_enabled: true,
                })}>Start Process</button>
                <button onClick={() => onStartProcessing({
                    transcribeMode: 'standard',
                    transcribeProvider: 'groq',
                    outputQuality: 'balanced',
                    outputResolution: '1080x1920',
                    width: 1920,
                    height: 1080,
                    duration: 10,
                    sourceDurationSeconds: 10,
                    subtitle_position: 16,
                    max_subtitle_lines: 2,
                    watermark_enabled: true,
                })}>Start External Process</button>
                <button onClick={() => onReprocessJob('job1', {
                    transcribeMode: 'standard',
                    transcribeProvider: 'groq',
                    outputQuality: 'balanced',
                    outputResolution: '1080x1920',
                    width: 1920,
                    height: 1080,
                    duration: 10,
                    sourceDurationSeconds: 10,
                    subtitle_position: 16,
                    max_subtitle_lines: 2,
                    watermark_enabled: true,
                })}>Reprocess</button>
                {onCancelProcessing && (
                    <button onClick={onCancelProcessing}>Cancel Active Process</button>
                )}
                <button onClick={onReset}>Reset</button>
            </div>
        );
    },
}));

jest.mock('@/components/AccountView', () => ({
    AccountView: ({ onSaveProfile, onLogout, onRefreshJobs, accountError }: { onSaveProfile: (name: string, pass1: string, pass2: string) => void; onLogout: () => Promise<void>; onRefreshJobs?: () => void | Promise<void>; accountError?: string }) => (
        <div data-testid="account-view">
            <button data-testid="save-profile-btn" onClick={() => onSaveProfile('NewName', 'pass', 'pass')}>Save Profile</button>
            <button data-testid="save-mismatch-btn" onClick={() => onSaveProfile('Test User', 'pass', 'different')}>Save Mismatch</button>
            <button data-testid="save-name-only-btn" onClick={() => onSaveProfile('NewName', '', '')}>Save Name Only</button>
            <button type="button" onClick={() => void onLogout()}>Sign out</button>
            {accountError && <p>{accountError}</p>}
            <button data-testid="refresh-jobs-btn" onClick={() => onRefreshJobs?.()}>Refresh Jobs</button>
        </div>
    ),
}));

describe('DashboardPage', () => {
    const mockUser = { id: '1', name: 'Test User', email: 'test@example.com', provider: 'local' };
    const mockLoadJobs = jest.fn();
    const mockRefreshUser = jest.fn();
    const mockRetrySession = jest.fn();
    const mockLogin = jest.fn();
    const mockRegister = jest.fn();
    const mockSetSelectedJob = jest.fn();
    const {
        __setBalanceMock,
        __setWalletMock,
        __refreshBalanceMock,
        __setPointsStateMock,
        __resetPointsStateMock,
    } = jest.requireMock('@/context/PointsContext') as {
        __setBalanceMock: jest.Mock;
        __setWalletMock: jest.Mock;
        __refreshBalanceMock: jest.Mock;
        __setPointsStateMock: (state: {
            balance?: number;
            paidBalance?: number;
            promotionalBalance?: number;
            reversalDebt?: number;
            aiSpendableBalance?: number;
        }) => void;
        __resetPointsStateMock: () => void;
    };

    beforeEach(() => {
        jest.clearAllMocks();
        window.localStorage.clear();
        window.history.replaceState({}, '', '/');
        capturedOnReset = null;
        capturedPollingCallbacks = null;
        capturedPollingJobId = null;
        mockPaidCreditLegalPublication.approved = false;
        __resetPointsStateMock();
        (useAuth as jest.Mock).mockReturnValue({
            user: mockUser,
            isLoading: false,
            sessionUnavailable: false,
            refreshUser: mockRefreshUser,
            retrySession: mockRetrySession,
            logout: jest.fn(),
            login: mockLogin,
            register: mockRegister,
        });
        (api.getPointsBalance as jest.Mock).mockResolvedValue({ balance: 125 });
        (api.getCreditCatalog as jest.Mock).mockResolvedValue({
            catalog_version: 'video-credits-v1',
            currency: 'eur',
            billing_country_scope: ['GR'],
            checkout_enabled: false,
            consumer_contract_status: 'unavailable_unapproved',
            consumer_contract: null,
            packages: [
                { key: 'starter', credits: 100, amount_eur_cents: 100, featured: false },
            ],
            video_pricing: [
                { key: 'up_to_3m', max_duration_seconds: 180, credits: 30 },
                { key: 'up_to_6m', max_duration_seconds: 360, credits: 60 },
                { key: 'up_to_10m', max_duration_seconds: 600, credits: 100 },
            ],
        });
        (useJobs as jest.Mock).mockReturnValue({
            selectedJob: null,
            setSelectedJob: mockSetSelectedJob,
            recentJobs: [],
            jobsLoading: false,
            jobsError: '',
            loadJobs: mockLoadJobs,
        });
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    async function confirmProcessingCost() {
        expect(screen.getByRole('dialog', { name: 'processingGateCostTitle' })).toBeInTheDocument();
        const confirmButton = screen.getByRole('button', { name: 'processingGateConfirm' });
        await waitFor(() => expect(confirmButton).toBeEnabled());
        await act(async () => {
            fireEvent.click(confirmButton);
            await Promise.resolve();
        });
    }

    it('renders dashboard components', () => {
        render(<DashboardPage />);

        expect(screen.getByText('heroTitle')).toBeInTheDocument();
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
        expect(screen.getByLabelText('profileLabel')).toBeInTheDocument();
        expect(screen.getByTestId('beta-badge')).toHaveTextContent('betaBadge');
        expect(screen.getByText('betaTestingNotice')).toBeInTheDocument();
        expect(mockLoadJobs).not.toHaveBeenCalled();
    });

    it('renders the Google profile picture with an initial fallback', () => {
        // REGRESSION: authenticated Google users only saw their initial even
        // though Google provided a verified profile picture.
        (useAuth as jest.Mock).mockReturnValue({
            user: {
                ...mockUser,
                provider: 'google',
                avatar_url: 'https://lh3.googleusercontent.com/a/avatar=s96-c',
            },
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout: jest.fn(),
            login: mockLogin,
            register: mockRegister,
        });

        render(<DashboardPage />);

        const profileButton = screen.getByRole('button', { name: 'profileLabel' });
        const avatar = within(profileButton).getByTestId('profile-avatar-image');
        expect(avatar).toHaveAttribute(
            'src',
            'https://lh3.googleusercontent.com/a/avatar=s96-c',
        );
        expect(avatar).toHaveAttribute('referrerpolicy', 'no-referrer');

        fireEvent.error(avatar);

        expect(within(profileButton).queryByTestId('profile-avatar-image'))
            .not.toBeInTheDocument();
        expect(profileButton).toHaveTextContent('T');
    });

    it('does not restore a completed job whose preview artifacts are missing', async () => {
        window.localStorage.setItem('lastActiveJobId', 'missing-job');
        (api.getJobStatus as jest.Mock).mockResolvedValue({
            id: 'missing-job',
            status: 'completed',
            result_data: {
                video_path: 'missing.mp4',
                files_missing: true,
            },
        });

        render(<DashboardPage />);

        await waitFor(() => {
            expect(api.getJobStatus).toHaveBeenCalledWith('missing-job');
        });
        expect(mockSetSelectedJob).not.toHaveBeenCalled();
        expect(window.localStorage.getItem('lastActiveJobId')).toBeNull();
    });

    it.each([
        ['pending', true],
        ['processing', true],
        ['cancelling', false],
    ])(
        'restores a %s job as active and resumes polling',
        async (status, isCancellable) => {
            // REGRESSION: restoring an active job only selected the stale job
            // snapshot, leaving jobId null so polling never resumed.
            window.localStorage.setItem('lastActiveJobId', 'active-job');
            (api.getJobStatus as jest.Mock).mockResolvedValue({
                id: 'active-job',
                status,
                progress: 42,
                message: 'Still working',
                result_data: null,
            });

            render(<DashboardPage />);

            await waitFor(() => {
                expect(capturedPollingJobId).toBe('active-job');
                expect(screen.getByTestId('process-processing')).toHaveTextContent('true');
            });
            expect(mockSetSelectedJob).not.toHaveBeenCalled();
            if (isCancellable) {
                expect(screen.getByText('Cancel Active Process')).toBeInTheDocument();
            } else {
                expect(screen.queryByText('Cancel Active Process')).not.toBeInTheDocument();
                expect(screen.getByTestId('process-status')).toHaveTextContent('cancellationRequested');
            }
        },
    );

    it('keeps history out of the header and opens it from the profile panel', () => {
        render(<DashboardPage />);

        const studioHeader = screen.getByRole('banner', { name: 'gsubs studio' });
        expect(studioHeader).toBeInTheDocument();
        // REGRESSION: The owner-selected stacked logo was replaced by a
        // horizontal compact-split pill.
        expect(within(studioHeader).getByRole('img', { name: 'gsubs' }))
            .toHaveAttribute('src', '/brand/gsubs-logo.svg');
        expect(screen.queryByRole('navigation', { name: 'Workspace navigation' }))
            .not.toBeInTheDocument();
        expect(within(studioHeader).queryByRole('button', { name: 'historyTitle' }))
            .not.toBeInTheDocument();
        expect(screen.getByTestId('studio-intro')).toHaveClass('studio-intro');
        expect(screen.getByTestId('studio-header-credits')).toBeInTheDocument();
        expect(screen.getByTestId('credits-coin-icon')).toBeInTheDocument();
        expect(screen.getByTestId('credits-balance')).toHaveTextContent('125');
        expect(studioHeader).not.toHaveTextContent('Mock');
        expect(studioHeader).not.toHaveTextContent('€0');
        expect(screen.queryByText('accountSettingsTitle')).not.toBeInTheDocument();
        expect(screen.queryByText('2026 REMAKE')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'switchLanguage' })).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'profileLabel' }));
        fireEvent.click(screen.getByRole('button', { name: 'historyTitle' }));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();
        expect(studioHeader).toHaveAttribute('aria-hidden', 'true');
        expect(studioHeader).toHaveAttribute('inert');
        expect(screen.queryByRole('button', { name: 'switchLanguage' })).not.toBeInTheDocument();
    });

    it('asks before the logo closes an active workspace and only leaves after confirmation', () => {
        // REGRESSION: the brand link navigated immediately even while a completed
        // project was open, without giving the user a chance to keep editing.
        window.localStorage.setItem('lastActiveJobId', 'job-open-in-editor');
        (useJobs as jest.Mock).mockReturnValue({
            selectedJob: {
                id: 'job-open-in-editor',
                status: 'completed',
                result_data: { video_path: 'processed.mp4' },
            },
            setSelectedJob: mockSetSelectedJob,
            recentJobs: [],
            jobsLoading: false,
            jobsError: '',
            loadJobs: mockLoadJobs,
        });
        window.scrollTo = jest.fn();

        render(<DashboardPage />);

        const homeLink = screen.getByRole('link', { name: 'brandHomeLabel' });
        fireEvent.click(homeLink);

        expect(screen.getByRole('dialog', { name: 'homeNavigationModalTitle' }))
            .toBeInTheDocument();
        expect(mockSetSelectedJob).not.toHaveBeenCalled();
        expect(window.localStorage.getItem('lastActiveJobId')).toBe('job-open-in-editor');

        fireEvent.click(screen.getByRole('button', { name: 'homeNavigationCancel' }));
        expect(screen.queryByRole('dialog', { name: 'homeNavigationModalTitle' }))
            .not.toBeInTheDocument();
        expect(mockSetSelectedJob).not.toHaveBeenCalled();

        fireEvent.click(homeLink);
        fireEvent.click(screen.getByRole('button', { name: 'homeNavigationConfirm' }));

        expect(mockSetSelectedJob).toHaveBeenCalledWith(null);
        expect(window.localStorage.getItem('lastActiveJobId')).toBeNull();
        expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
    });

    it('keeps the logo as a direct home link when no work is active', () => {
        render(<DashboardPage />);

        const homeLink = screen.getByRole('link', { name: 'brandHomeLabel' });
        expect(homeLink).toHaveAttribute('href', '/');
        expect(screen.queryByRole('dialog', { name: 'homeNavigationModalTitle' }))
            .not.toBeInTheDocument();
    });

    it('protects a selected upload before processing has started', () => {
        // REGRESSION: work only counted after a server job existed, so a file
        // selected locally could be discarded by the logo without warning.
        window.scrollTo = jest.fn();
        render(<DashboardPage />);

        fireEvent.click(screen.getByRole('button', { name: 'Select File' }));
        fireEvent.click(screen.getByRole('link', { name: 'brandHomeLabel' }));

        expect(screen.getByRole('dialog', { name: 'homeNavigationModalTitle' }))
            .toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'homeNavigationCancel' }));
    });

    // REGRESSION: the disabled production UI exposed prices and a purchase
    // dialog even though paid-credit legal publication was not approved.
    it('keeps the balance visible without exposing a purchase entry point', () => {
        render(<DashboardPage />);

        fireEvent.click(screen.getByRole('button', { name: 'creditsLabel: 125' }));

        expect(screen.getByTestId('credits-balance')).toHaveTextContent('125');
        expect(__refreshBalanceMock).toHaveBeenCalledTimes(1);
        expect(screen.queryByRole('dialog', {
            name: 'creditPurchaseTitle',
        })).not.toBeInTheDocument();
        expect(screen.queryByText(/€(?:1|3|10)\.00/)).not.toBeInTheDocument();
        expect(api.getCreditCatalog).not.toHaveBeenCalled();
    });

    it('opens the purchase dialog only after code-owned publication approval', async () => {
        mockPaidCreditLegalPublication.approved = true;
        render(<DashboardPage />);

        fireEvent.click(screen.getByRole('button', { name: 'creditsLabel: 125' }));

        expect(await screen.findByRole('dialog', {
            name: 'creditPurchaseTitle',
        })).toBeInTheDocument();
        expect(api.getCreditCatalog).toHaveBeenCalledTimes(1);
    });

    it.each(['paid', 'partially_refunded'])(
        'reconciles an already-%s checkout, refreshes the wallet, and clears the return URL',
        async (status) => {
            const sessionId = `cs_test_${status}`;
            const wallet = {
                balance: 225,
                paid_balance: 100,
                promotional_balance: 125,
                reversal_debt: 0,
                ai_spendable_balance: 100,
            };
            window.history.replaceState(
                {},
                '',
                `/?checkout=success&session_id=${sessionId}`,
            );
            (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
                purchase_id: `purchase-${status}`,
                package_key: 'starter',
                credits: 100,
                amount_eur_cents: 100,
                status,
                checkout_session_id: sessionId,
                wallet,
            });

            render(<DashboardPage />);

            expect(await screen.findByRole('status')).toHaveTextContent('creditPurchaseSuccess');
            expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
            expect(__setWalletMock).toHaveBeenCalledWith(wallet);
            expect(screen.getByRole('link', { name: 'billingContractDownload' })).toBeInTheDocument();
            await waitFor(() => {
                expect(window.location.search).toBe('');
            });
        },
    );

    it('cleans a cancelled checkout once while preserving unrelated URL state', async () => {
        window.history.replaceState(
            {},
            '',
            '/?checkout=cancelled&session_id=cs_test_cancelled&campaign=beta#credits',
        );

        render(<DashboardPage />);

        expect(await screen.findByRole('status')).toHaveTextContent('creditPurchaseCancelled');
        expect(api.getCreditCheckoutStatus).not.toHaveBeenCalled();
        expect(window.location.search).toBe('?campaign=beta');
        expect(window.location.hash).toBe('#credits');
    });

    it('keeps every known nonterminal checkout status until it becomes paid', async () => {
        jest.useFakeTimers();
        const sessionId = 'cs_test_pending_then_paid';
        const pendingWallet = {
            balance: 125,
            paid_balance: 0,
            promotional_balance: 125,
            reversal_debt: 0,
            ai_spendable_balance: 0,
        };
        const paidWallet = {
            balance: 225,
            paid_balance: 100,
            promotional_balance: 125,
            reversal_debt: 0,
            ai_spendable_balance: 100,
        };
        window.history.replaceState(
            {},
            '',
            `/?checkout=success&session_id=${sessionId}`,
        );
        (api.getCreditCheckoutStatus as jest.Mock)
            .mockResolvedValueOnce({
                purchase_id: 'purchase-pending',
                package_key: 'starter',
                credits: 100,
                amount_eur_cents: 100,
                status: 'creating',
                checkout_session_id: sessionId,
                wallet: pendingWallet,
            })
            .mockResolvedValueOnce({
                purchase_id: 'purchase-pending',
                package_key: 'starter',
                credits: 100,
                amount_eur_cents: 100,
                status: 'checkout_created',
                checkout_session_id: sessionId,
                wallet: pendingWallet,
            })
            .mockResolvedValueOnce({
                purchase_id: 'purchase-pending',
                package_key: 'starter',
                credits: 100,
                amount_eur_cents: 100,
                status: 'awaiting_payment',
                checkout_session_id: sessionId,
                wallet: pendingWallet,
            })
            .mockResolvedValueOnce({
                purchase_id: 'purchase-pending',
                package_key: 'starter',
                credits: 100,
                amount_eur_cents: 100,
                status: 'paid',
                checkout_session_id: sessionId,
                wallet: paidWallet,
            });

        render(<DashboardPage />);

        await act(async () => {
            await Promise.resolve();
        });
        expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
        expect(screen.getByRole('status')).toHaveTextContent('creditPurchasePending');
        expect(window.location.search).toContain('session_id=cs_test_pending_then_paid');

        await act(async () => {
            jest.advanceTimersByTime(1_000);
            await Promise.resolve();
        });
        expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(2);
        expect(screen.getByRole('status')).toHaveTextContent('creditPurchasePending');
        expect(window.location.search).toContain('session_id=cs_test_pending_then_paid');

        await act(async () => {
            jest.advanceTimersByTime(2_000);
            await Promise.resolve();
        });
        expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(3);
        expect(screen.getByRole('status')).toHaveTextContent('creditPurchasePending');
        expect(window.location.search).toContain('session_id=cs_test_pending_then_paid');

        await act(async () => {
            jest.advanceTimersByTime(4_000);
            await Promise.resolve();
        });

        expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(4);
        expect(screen.getByRole('status')).toHaveTextContent('creditPurchaseSuccess');
        expect(__setWalletMock).toHaveBeenLastCalledWith(paidWallet);
        expect(window.location.search).toBe('');
    });

    it('preserves a slow checkout session and provides a bounded manual retry', async () => {
        jest.useFakeTimers();
        const sessionId = 'cs_test_slow_pending';
        const pendingStatus = {
            purchase_id: 'purchase-slow',
            package_key: 'starter',
            credits: 100,
            amount_eur_cents: 100,
            status: 'future_provider_pending_state',
            checkout_session_id: sessionId,
            wallet: {
                balance: 125,
                paid_balance: 0,
                promotional_balance: 125,
                reversal_debt: 0,
                ai_spendable_balance: 0,
            },
        };
        window.history.replaceState(
            {},
            '',
            `/?checkout=success&session_id=${sessionId}`,
        );
        (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue(pendingStatus);

        render(<DashboardPage />);

        await act(async () => {
            await Promise.resolve();
            await jest.runAllTimersAsync();
        });

        expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(6);
        expect(screen.getByRole('status')).toHaveTextContent('creditPurchasePendingRetry');
        expect(screen.getByRole('button', { name: 'creditPurchaseRetry' })).toBeInTheDocument();
        expect(window.location.search).toContain('session_id=cs_test_slow_pending');

        (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValueOnce({
            ...pendingStatus,
            status: 'paid',
            wallet: {
                ...pendingStatus.wallet,
                balance: 225,
                paid_balance: 100,
                ai_spendable_balance: 100,
            },
        });
        fireEvent.click(screen.getByRole('button', { name: 'creditPurchaseRetry' }));
        await act(async () => {
            await Promise.resolve();
        });

        expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(7);
        expect(screen.getByRole('status')).toHaveTextContent('creditPurchaseSuccess');
        expect(window.location.search).toBe('');
    });

    it('cancels delayed checkout polling when the dashboard unmounts', async () => {
        jest.useFakeTimers();
        const sessionId = 'cs_test_unmounted_pending';
        window.history.replaceState(
            {},
            '',
            `/?checkout=success&session_id=${sessionId}`,
        );
        (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
            purchase_id: 'purchase-unmounted',
            package_key: 'starter',
            credits: 100,
            amount_eur_cents: 100,
            status: 'awaiting_payment',
            checkout_session_id: sessionId,
            wallet: {
                balance: 125,
                paid_balance: 0,
                promotional_balance: 125,
                reversal_debt: 0,
                ai_spendable_balance: 0,
            },
        });

        const { unmount } = render(<DashboardPage />);
        await act(async () => {
            await Promise.resolve();
        });
        expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);

        unmount();
        await act(async () => {
            await jest.runAllTimersAsync();
        });

        expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
        expect(window.location.search).toContain('session_id=cs_test_unmounted_pending');
    });

    it.each([
        ['failed', 'creditPurchaseFailed'],
        ['expired', 'creditPurchaseExpired'],
    ])(
        'shows a terminal notice when Stripe checkout is %s',
        async (status, expectedNotice) => {
            window.history.replaceState(
                {},
                '',
                `/?checkout=success&session_id=cs_test_${status}`,
            );
            (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
                purchase_id: `purchase-${status}`,
                package_key: 'starter',
                credits: 100,
                amount_eur_cents: 100,
                status,
                checkout_session_id: `cs_test_${status}`,
                wallet: {
                    balance: 100,
                    paid_balance: 0,
                    promotional_balance: 100,
                    reversal_debt: 0,
                    ai_spendable_balance: 0,
                },
            });

            render(<DashboardPage />);

            expect(await screen.findByRole('status')).toHaveTextContent(expectedNotice);
            expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
            expect(__setWalletMock).toHaveBeenCalledWith(expect.objectContaining({
                balance: 100,
            }));
            expect(screen.queryByText('creditPurchasePending')).not.toBeInTheDocument();
            expect(window.location.search).toBe('');
        },
    );

    // REGRESSION: owner-reachable reversed and disputed purchases fell through
    // to the unknown-status path, which polled them forever as if they were
    // pending and retained stale checkout return parameters.
    it.each([
        [
            'reversed',
            'creditPurchaseReversed',
            {
                balance: 25,
                paid_balance: 0,
                promotional_balance: 25,
                reversal_debt: 0,
                ai_spendable_balance: 0,
            },
        ],
        [
            'disputed',
            'creditPurchaseDisputed',
            {
                balance: 0,
                paid_balance: 0,
                promotional_balance: 0,
                reversal_debt: 75,
                ai_spendable_balance: 0,
            },
        ],
    ])(
        'settles a %s checkout return without retrying or starting another purchase',
        async (status, expectedNotice, wallet) => {
            jest.useFakeTimers();
            const sessionId = `cs_test_${status}`;
            window.history.replaceState(
                {},
                '',
                `/?checkout=success&session_id=${sessionId}&campaign=beta#credits`,
            );
            (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
                purchase_id: `purchase-${status}`,
                package_key: 'starter',
                credits: 100,
                amount_eur_cents: 100,
                status,
                checkout_session_id: sessionId,
                wallet,
            });

            render(<DashboardPage />);
            await act(async () => {
                await Promise.resolve();
            });

            expect(screen.getByRole('status')).toHaveTextContent(expectedNotice);
            expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
            expect(__setWalletMock).toHaveBeenCalledWith(wallet);
            expect(api.createCreditCheckout).not.toHaveBeenCalled();
            expect(screen.queryByRole('button', { name: 'creditPurchaseRetry' }))
                .not.toBeInTheDocument();
            expect(screen.queryByRole('link', { name: 'billingContractDownload' }))
                .not.toBeInTheDocument();
            expect(window.location.search).toBe('?campaign=beta');
            expect(window.location.hash).toBe('#credits');
        },
    );

    it('opens account settings only from the profile avatar', () => {
        render(<DashboardPage />);

        expect(screen.queryByText('accountSettingsTitle')).not.toBeInTheDocument();
        const opener = screen.getByRole('button', { name: 'profileLabel' });
        opener.focus();
        fireEvent.click(opener);
        expect(screen.getByTestId('account-view')).toBeInTheDocument();
    });

    it('locks both document scrollers while the account dialog is open', () => {
        const scrollTo = jest.fn();
        Object.defineProperty(window, 'scrollTo', {
            configurable: true,
            value: scrollTo,
        });
        Object.defineProperty(window, 'scrollX', { configurable: true, value: 11 });
        Object.defineProperty(window, 'scrollY', { configurable: true, value: 355 });
        document.documentElement.style.overflow = 'clip';
        document.body.style.overflow = 'auto';

        render(<DashboardPage />);
        fireEvent.click(screen.getByRole('button', { name: 'profileLabel' }));

        expect(document.documentElement.style.overflow).toBe('hidden');
        expect(document.documentElement.style.overscrollBehavior).toBe('none');
        expect(document.body.style.overflow).toBe('hidden');
        expect(document.body.style.position).toBe('fixed');
        expect(document.body.style.top).toBe('-355px');
        expect(document.body.style.left).toBe('-11px');

        fireEvent.click(within(
            screen.getByRole('dialog', { name: 'accountSettingsTitle' }),
        ).getByRole('button', { name: 'closeLabel' }));

        expect(document.documentElement.style.overflow).toBe('clip');
        expect(document.body.style.overflow).toBe('auto');
        expect(document.body.style.position).toBe('');
        expect(scrollTo).toHaveBeenCalledWith(11, 355);

        document.documentElement.removeAttribute('style');
        document.body.removeAttribute('style');
    });

    it('closes the account dialog with Escape and restores focus to its opener', async () => {
        render(<DashboardPage />);

        const opener = screen.getByRole('button', { name: 'profileLabel' });
        opener.focus();
        fireEvent.click(opener);
        const dialog = screen.getByRole('dialog', { name: 'accountSettingsTitle' });
        const closeButton = within(dialog).getByRole('button', { name: 'closeLabel' });

        await waitFor(() => expect(closeButton).toHaveFocus());
        fireEvent.keyDown(document, { key: 'Escape' });

        await waitFor(() => {
            expect(screen.queryByRole('dialog', { name: 'accountSettingsTitle' }))
                .not.toBeInTheDocument();
            expect(opener).toHaveFocus();
        });
    });

    // REGRESSION: logging out from the open account panel left the header inert,
    // so the guest "Sign in" link was visible but could not be clicked.
    it('restores an interactive sign-in link after logout from the account panel', async () => {
        let currentUser: typeof mockUser | null = mockUser;
        const logout = jest.fn(() => {
            currentUser = null;
        });
        (useAuth as jest.Mock).mockImplementation(() => ({
            user: currentUser,
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout,
            login: mockLogin,
            register: mockRegister,
        }));

        const { rerender } = render(<DashboardPage />);
        fireEvent.click(screen.getByRole('button', { name: 'profileLabel' }));
        fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
        await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
        rerender(<DashboardPage />);

        const studioHeader = screen.getByLabelText('gsubs studio');
        expect(studioHeader).not.toHaveAttribute('inert');
        expect(studioHeader).not.toHaveAttribute('aria-hidden');
        expect(screen.getByRole('link', { name: 'guestSignIn' }))
            .toHaveAttribute('href', '/login');
    });

    it('keeps the account session visible when server logout is not confirmed', async () => {
        const logout = jest.fn().mockRejectedValue(new Error('offline'));
        (useAuth as jest.Mock).mockReturnValue({
            user: mockUser,
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout,
            login: mockLogin,
            register: mockRegister,
        });

        render(<DashboardPage />);
        fireEvent.click(screen.getByRole('button', { name: 'profileLabel' }));
        fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

        await waitFor(() => {
            expect(logout).toHaveBeenCalledTimes(1);
            expect(screen.getByText('signOutError')).toBeInTheDocument();
        });
        expect(screen.getByRole('dialog', { name: 'accountSettingsTitle' }))
            .toBeInTheDocument();
        expect(screen.getByLabelText('profileLabel'))
            .toBeInTheDocument();
    });

    it('renders footer with privacy and terms links', () => {
        render(<DashboardPage />);

        const privacyLink = screen.getByText('legalPrivacyLink');
        const termsLink = screen.getByText('legalTermsLink');

        expect(privacyLink).toBeInTheDocument();
        expect(privacyLink.closest('a')).toHaveAttribute('href', '/privacy');

        expect(termsLink).toBeInTheDocument();
        expect(termsLink.closest('a')).toHaveAttribute('href', '/terms');
        expect(screen.getByRole('link', { name: /gsubs by Ascentia/i }))
            .toHaveAttribute('href', 'https://ascentia-gp.com/');
    });

    it('shows loading state when isLoading is true', () => {
        (useAuth as jest.Mock).mockReturnValue({
            user: null,
            isLoading: true,
            sessionUnavailable: false,
            refreshUser: mockRefreshUser,
            retrySession: mockRetrySession,
            logout: jest.fn(),
        });

        render(<DashboardPage />);
        const loadingState = screen.getByRole('status');
        expect(loadingState).toHaveAttribute('aria-live', 'polite');
        expect(loadingState).toHaveAttribute('aria-busy', 'true');
        expect(within(loadingState).getByRole('img', { name: 'gsubs' })).toBeInTheDocument();
        expect(within(loadingState).getByText('loading')).toBeInTheDocument();
    });

    it('replaces an unbounded loading state with session recovery', () => {
        // REGRESSION: transient session verification failures previously left
        // the dashboard on the loading screen with no user action available.
        (useAuth as jest.Mock).mockReturnValue({
            user: null,
            isLoading: false,
            sessionUnavailable: true,
            refreshUser: mockRefreshUser,
            retrySession: mockRetrySession,
            logout: jest.fn(),
        });

        render(<DashboardPage />);

        expect(screen.getByRole('heading', { name: 'sessionUnavailableTitle' }))
            .toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'sessionRetry' }));
        expect(mockRetrySession).toHaveBeenCalledTimes(1);
        expect(screen.queryByText('loading')).not.toBeInTheDocument();
    });

    it('renders the upload workspace for guests without redirecting', () => {
        (useAuth as jest.Mock).mockReturnValue({
            user: null,
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout: jest.fn(),
            login: mockLogin,
            register: mockRegister,
        });

        render(<DashboardPage />);

        expect(screen.getByTestId('process-view')).toBeInTheDocument();
        const signInLink = screen.getByRole('link', { name: 'guestSignIn' });
        expect(signInLink).toHaveAttribute('href', '/login');
        expect(screen.queryByLabelText('profileLabel')).not.toBeInTheDocument();
        expect(screen.queryByTestId('studio-header-credits')).not.toBeInTheDocument();
    });

    it('keeps the guest file selected through login and asks for cost before processing', async () => {
        (useAuth as jest.Mock).mockReturnValue({
            user: null,
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout: jest.fn(),
            login: mockLogin,
            register: mockRegister,
        });
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });

        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));

        expect(screen.getByRole('dialog', { name: 'processingGateAuthTitle' })).toBeInTheDocument();
        expect(api.processVideo).not.toHaveBeenCalled();

        fireEvent.change(screen.getByLabelText('loginEmailLabel'), { target: { value: 'guest@example.com' } });
        fireEvent.change(screen.getByLabelText('loginPasswordLabel'), { target: { value: 'correct horse battery staple' } });
        fireEvent.click(screen.getByRole('button', { name: 'processingGateLoginSubmit' }));

        await waitFor(() => {
            expect(mockLogin).toHaveBeenCalledWith('guest@example.com', 'correct horse battery staple');
            expect(api.getPointsBalance).toHaveBeenCalled();
        });

        expect(screen.getByRole('dialog', { name: 'processingGateCostTitle' })).toBeInTheDocument();
        expect(api.processVideo).not.toHaveBeenCalled();

        await confirmProcessingCost();

        await waitFor(() => expect(api.processVideo).toHaveBeenCalledWith(
            expect.any(File),
            expect.any(Object),
            expect.any(Object),
        ));
    });

    it('handles start processing success', async () => {
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending', balance: 800 });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });
        expect(api.processVideo).toHaveBeenCalledWith(
            expect.any(File),
            expect.objectContaining({
                authorized_credits: 30,
                watermark_enabled: true,
            }),
            expect.objectContaining({
                onProgress: expect.any(Function),
                onUploadComplete: expect.any(Function),
                signal: expect.any(AbortSignal),
            }),
        );
        expect(__setBalanceMock).toHaveBeenCalledWith(800);
    });

    it('reconfirms an authoritative 30-to-60 quote change before one explicit retry', async () => {
        // REGRESSION: a measured duration just above three minutes must never
        // auto-retry at a higher credit ceiling without the user's new consent.
        (api.processVideo as jest.Mock)
            .mockRejectedValueOnce(Object.assign(new Error('Processing quote changed'), {
                status: 409,
                code: 'PROCESSING_QUOTE_CHANGED',
                details: {
                    duration_seconds: 180.001,
                    required_credits: 60,
                },
            }))
            .mockResolvedValueOnce({ id: 'job-quote-confirmed', status: 'pending' });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        const updatedDialog = await screen.findByRole('dialog', {
            name: 'processingGateCostTitle',
        });
        expect(within(updatedDialog).getByText('60')).toBeInTheDocument();
        expect(within(updatedDialog).getByRole('alert')).toHaveTextContent(
            'processingGateQuoteChanged',
        );
        expect(api.processVideo).toHaveBeenCalledTimes(1);
        const firstCall = (api.processVideo as jest.Mock).mock.calls[0];
        expect(firstCall[1]).toEqual(expect.objectContaining({
            authorized_credits: 30,
        }));

        await act(async () => {
            await Promise.resolve();
        });
        expect(api.processVideo).toHaveBeenCalledTimes(1);

        await confirmProcessingCost();
        await waitFor(() => expect(api.processVideo).toHaveBeenCalledTimes(2));

        const secondCall = (api.processVideo as jest.Mock).mock.calls[1];
        expect(secondCall[0]).toBe(firstCall[0]);
        expect(secondCall[1]).toEqual(expect.objectContaining({
            authorized_credits: 60,
        }));
        const { authorized_credits: firstCredits, ...firstSettings } = firstCall[1];
        const { authorized_credits: secondCredits, ...secondSettings } = secondCall[1];
        expect(firstCredits).toBe(30);
        expect(secondCredits).toBe(60);
        expect(secondSettings).toEqual(firstSettings);
    });

    it('reconfirms an authoritative reprocess quote change before one explicit retry', async () => {
        // REGRESSION: reprocessing uses the same fail-closed consent boundary
        // as a new upload and must retain the source job and all settings.
        (api.reprocessJob as jest.Mock)
            .mockRejectedValueOnce(Object.assign(new Error('Processing quote changed'), {
                status: 409,
                code: 'PROCESSING_QUOTE_CHANGED',
                details: {
                    duration_seconds: 180.001,
                    required_credits: 60,
                },
            }))
            .mockResolvedValueOnce({ id: 'job-reprocess-quote-confirmed', status: 'pending' });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Reprocess'));
        await confirmProcessingCost();

        const updatedDialog = await screen.findByRole('dialog', {
            name: 'processingGateCostTitle',
        });
        expect(within(updatedDialog).getByText('60')).toBeInTheDocument();
        expect(within(updatedDialog).getByRole('alert')).toHaveTextContent(
            'processingGateQuoteChanged',
        );
        expect(api.reprocessJob).toHaveBeenCalledTimes(1);
        const firstCall = (api.reprocessJob as jest.Mock).mock.calls[0];
        expect(firstCall[0]).toBe('job1');
        expect(firstCall[1]).toEqual(expect.objectContaining({
            authorized_credits: 30,
        }));

        await act(async () => {
            await Promise.resolve();
        });
        expect(api.reprocessJob).toHaveBeenCalledTimes(1);

        await confirmProcessingCost();
        await waitFor(() => expect(api.reprocessJob).toHaveBeenCalledTimes(2));

        const secondCall = (api.reprocessJob as jest.Mock).mock.calls[1];
        expect(secondCall[0]).toBe(firstCall[0]);
        expect(secondCall[1]).toEqual(expect.objectContaining({
            authorized_credits: 60,
        }));
        const { authorized_credits: firstCredits, ...firstSettings } = firstCall[1];
        const { authorized_credits: secondCredits, ...secondSettings } = secondCall[1];
        expect(firstCredits).toBe(30);
        expect(secondCredits).toBe(60);
        expect(secondSettings).toEqual(firstSettings);
    });

    it('uses promotional credits for mock processing', async () => {
        // REGRESSION: mock processing used aiSpendableBalance and blocked a
        // user with 100 promotional credits and zero purchased credits.
        __setPointsStateMock({
            balance: 100,
            paidBalance: 0,
            promotionalBalance: 100,
            reversalDebt: 0,
            aiSpendableBalance: 0,
        });
        (api.processVideo as jest.Mock).mockResolvedValue({
            id: 'job-mock',
            status: 'pending',
            balance: 70,
        });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));

        expect(screen.getByText('processingGateTotalBalanceLabel')).toBeInTheDocument();
        expect(screen.queryByText('processingGateBalanceLabel')).not.toBeInTheDocument();
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalledWith(
                expect.any(File),
                expect.objectContaining({ transcribe_provider: 'mock' }),
                expect.any(Object),
            );
        });
    });

    it('still requires purchased credits for an external provider', () => {
        __setPointsStateMock({
            balance: 100,
            paidBalance: 0,
            promotionalBalance: 100,
            reversalDebt: 0,
            aiSpendableBalance: 0,
        });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Reprocess'));

        expect(screen.getByText('processingGateBalanceLabel')).toBeInTheDocument();
        expect(screen.queryByRole('button', {
            name: 'processingGateConfirm',
        })).not.toBeInTheDocument();
        expect(api.reprocessJob).not.toHaveBeenCalled();
    });

    it('keeps production mock uploads on the local processing endpoint', async () => {
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalledWith(
                expect.any(File),
                expect.objectContaining({ transcribe_provider: 'mock' }),
                expect.any(Object),
            );
        });
    });

    it('shows direct-upload progress and only exposes cancellation while it is safe', async () => {
        type UploadCallbacks = {
            onProgress?: (percent: number) => void;
            onUploadComplete?: () => void;
            signal?: AbortSignal;
        };
        let uploadCallbacks: UploadCallbacks | undefined;
        let resolveProcess: ((job: { id: string; status: string }) => void) | undefined;
        (api.processVideo as jest.Mock).mockImplementation(
            (_file: File, _settings: unknown, callbacks: UploadCallbacks) => {
                uploadCallbacks = callbacks;
                return new Promise((resolve) => {
                    resolveProcess = resolve;
                });
            },
        );
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();
        await waitFor(() => expect(uploadCallbacks).toBeDefined());

        expect(screen.getByText('Cancel Active Process')).toBeInTheDocument();
        act(() => uploadCallbacks?.onProgress?.(37));
        expect(screen.getByTestId('process-progress')).toHaveTextContent('37');
        expect(screen.getByTestId('process-status')).toHaveTextContent('statusUploading 37%');

        act(() => uploadCallbacks?.onUploadComplete?.());
        expect(screen.queryByText('Cancel Active Process')).not.toBeInTheDocument();
        expect(screen.getByTestId('process-status')).toHaveTextContent('statusProcessing');

        await act(async () => {
            resolveProcess?.({ id: 'job-progress', status: 'pending' });
            await Promise.resolve();
        });
        expect(screen.getByText('Cancel Active Process')).toBeInTheDocument();
    });

    it('aborts a slow direct upload and keeps the selected file available', async () => {
        type UploadCallbacks = { signal?: AbortSignal };
        let uploadSignal: AbortSignal | undefined;
        (api.processVideo as jest.Mock).mockImplementation(
            (_file: File, _settings: unknown, callbacks: UploadCallbacks) => {
                uploadSignal = callbacks.signal;
                return new Promise((_resolve, reject) => {
                    callbacks.signal?.addEventListener('abort', () => {
                        reject(Object.assign(new Error('Upload cancelled'), {
                            code: 'upload_cancelled',
                        }));
                    }, { once: true });
                });
            },
        );
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();
        const cancelButton = await screen.findByText('Cancel Active Process');
        fireEvent.click(cancelButton);

        await waitFor(() => expect(uploadSignal?.aborted).toBe(true));
        expect(screen.getByTestId('process-error')).toHaveTextContent('processingCancelled');
        expect(screen.queryByText('Cancel Active Process')).not.toBeInTheDocument();
        expect(api.cancelJob).not.toHaveBeenCalled();
    });

    it('keeps polling a server job until cancellation cleanup is terminal', async () => {
        // REGRESSION: a successful cancel request previously cleared jobId and
        // stopped polling before the server had securely removed local files.
        (api.processVideo as jest.Mock).mockResolvedValue({
            id: 'job-cancel-server',
            status: 'pending',
        });
        (api.cancelJob as jest.Mock).mockResolvedValue({
            id: 'job-cancel-server',
            status: 'cancelling',
        });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        const cancelButton = await screen.findByText('Cancel Active Process');
        expect(capturedPollingJobId).toBe('job-cancel-server');
        expect(window.localStorage.getItem('lastActiveJobId')).toBe('job-cancel-server');
        fireEvent.click(cancelButton);

        await waitFor(() => {
            expect(api.cancelJob).toHaveBeenCalledWith('job-cancel-server');
            expect(screen.getByTestId('process-status')).toHaveTextContent('cancellationRequested');
        });
        expect(screen.getByTestId('process-processing')).toHaveTextContent('true');
        expect(screen.queryByText('Cancel Active Process')).not.toBeInTheDocument();
        expect(capturedPollingJobId).toBe('job-cancel-server');

        act(() => {
            capturedPollingCallbacks!.onProgress(50, 'cancellationRequested');
        });
        expect(capturedPollingJobId).toBe('job-cancel-server');
        expect(screen.getByTestId('process-processing')).toHaveTextContent('true');

        act(() => {
            // useJobPolling maps the terminal `cancelled` state to onFailed.
            capturedPollingCallbacks!.onFailed('processingCancelled');
        });
        await waitFor(() => {
            expect(capturedPollingJobId).toBeNull();
            expect(screen.getByTestId('process-processing')).toHaveTextContent('false');
            expect(screen.getByTestId('process-error')).toHaveTextContent('processingCancelled');
            expect(window.localStorage.getItem('lastActiveJobId')).toBeNull();
        });
    });

    it('uses the single local raw-stream client path for a production external provider', async () => {
        // REGRESSION: production external-provider uploads must stay on the
        // one local raw-stream client path with no cloud or multipart branch.
        (api.processVideo as jest.Mock).mockResolvedValue({
            id: 'job-local-production',
            status: 'pending',
        });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start External Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalledWith(
                expect.any(File),
                expect.objectContaining({ transcribe_provider: 'groq' }),
                expect.objectContaining({
                    onProgress: expect.any(Function),
                    onUploadComplete: expect.any(Function),
                    signal: expect.any(AbortSignal),
                }),
            );
        });
    });

    it('refreshes balance when process response has no balance', async () => {
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });
        expect(__refreshBalanceMock).toHaveBeenCalled();
    });

    it('handles start processing error', async () => {
        (api.processVideo as jest.Mock).mockRejectedValue(
            Object.assign(new Error('Upload failed'), { code: 'upload_network_error' }),
        );
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });
        expect(screen.getByTestId('process-error')).toHaveTextContent('uploadConnectionError');
    });

    it('refreshes refunded credits after the server terminates a stalled upload', async () => {
        (api.processVideo as jest.Mock).mockRejectedValue(
            Object.assign(new Error('Upload stalled before completion'), { status: 408 }),
        );
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });
        expect(screen.getByTestId('process-error')).toHaveTextContent('uploadConnectionError');
        expect(__refreshBalanceMock).toHaveBeenCalledTimes(1);
    });

    it('updates balance on reprocess success', async () => {
        (api.reprocessJob as jest.Mock).mockResolvedValue({ id: 'job234', status: 'pending', balance: 700 });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Reprocess'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.reprocessJob).toHaveBeenCalledWith('job1', expect.any(Object));
        });
        expect(api.reprocessJob).toHaveBeenCalledWith(
            'job1',
            expect.objectContaining({
                authorized_credits: 30,
                watermark_enabled: true,
            }),
        );
        expect(__setBalanceMock).toHaveBeenCalledWith(700);
    });

    it('handles profile save with name change', async () => {
        (api.updateProfile as jest.Mock).mockResolvedValue({});
        mockRefreshUser.mockResolvedValue({});

        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('profileLabel'));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Save Name Only'));

        await waitFor(() => {
            expect(api.updateProfile).toHaveBeenCalledWith('NewName');
            expect(mockRefreshUser).toHaveBeenCalled();
        });
    });

    it('handles profile save with password mismatch', async () => {
        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('profileLabel'));
        fireEvent.click(screen.getByText('Save Mismatch'));

        // Password mismatch error should be set but we can't easily verify internal state
        // The test verifies the code path is executed
        await waitFor(() => {
            expect(api.updateProfile).not.toHaveBeenCalled();
        });
    });

    it('handles profile save with password update', async () => {
        (api.updateProfile as jest.Mock).mockResolvedValue({});
        (api.updatePassword as jest.Mock).mockResolvedValue({});
        mockRefreshUser.mockResolvedValue({});

        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('profileLabel'));
        fireEvent.click(screen.getByText('Save Profile'));

        await waitFor(() => {
            expect(api.updateProfile).toHaveBeenCalledWith('NewName');
            expect(api.updatePassword).toHaveBeenCalledWith('pass', 'pass');
        });
    });

    it('handles profile save error', async () => {
        (api.updateProfile as jest.Mock).mockRejectedValue(new Error('Update failed'));

        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('profileLabel'));
        fireEvent.click(screen.getByText('Save Name Only'));

        await waitFor(() => {
            expect(api.updateProfile).toHaveBeenCalled();
        });
    });

    /**
     * REGRESSION: resetProcessing must clear selectedJob.
     * Bug: User uploaded a file, processed it, clicked Reset, uploaded a new file,
     * but the previous job's title was still shown in the Live Output section.
     * Fix: Added setSelectedJob(null) to resetProcessing function.
     */
    it('handles reset processing and clears selectedJob', async () => {
        window.localStorage.setItem('lastActiveJobId', 'previous-job');
        render(<DashboardPage />);

        // Trigger reset via captured callback
        fireEvent.click(await screen.findByText('Reset'));

        // Test verifies the code path is executed without errors
        expect(capturedOnReset).toBeDefined();

        // REGRESSION: Verify that setSelectedJob(null) is called to clear previous job
        expect(mockSetSelectedJob).toHaveBeenCalledWith(null);
        expect(window.localStorage.getItem('lastActiveJobId')).toBeNull();
    });

    it('calls refreshActivity via refresh button', async () => {
        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('profileLabel'));
        fireEvent.click(screen.getByTestId('refresh-jobs-btn'));

        await waitFor(() => {
            expect(mockLoadJobs).toHaveBeenCalledTimes(1);
        });
    });

    it('handles polling onProgress callback', () => {
        render(<DashboardPage />);

        // The component should have passed callbacks to useJobPolling
        expect(capturedPollingCallbacks).not.toBeNull();

        // Invoke the onProgress callback
        act(() => {
            capturedPollingCallbacks!.onProgress(50, 'Processing...');
        });

        // Component should update without errors
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
    });

    it('handles polling onComplete callback', async () => {
        render(<DashboardPage />);

        const mockJob = { id: 'job1', status: 'completed', result_data: { public_url: 'url' } };

        act(() => {
            capturedPollingCallbacks!.onComplete(mockJob);
        });

        await waitFor(() => {
            expect(mockSetSelectedJob).toHaveBeenCalledWith(mockJob);
        });
        expect(mockLoadJobs).toHaveBeenCalled();
    });

    it('handles polling onFailed callback', async () => {
        render(<DashboardPage />);

        act(() => {
            capturedPollingCallbacks!.onFailed('Job failed');
        });

        await waitFor(() => {
            expect(mockLoadJobs).toHaveBeenCalled();
        });
    });

    it('localizes a missing word-timestamps failure and refreshes refunded credits', async () => {
        render(<DashboardPage />);
        __refreshBalanceMock.mockClear();

        act(() => {
            capturedPollingCallbacks!.onFailed(
                'ElevenLabs Scribe v2 response did not include word timestamps.',
            );
        });

        await waitFor(() => {
            expect(screen.getByTestId('process-error')).toHaveTextContent(
                'transcriptionMissingWordTimestamps',
            );
            expect(__refreshBalanceMock).toHaveBeenCalledTimes(1);
        });
        expect(screen.getByTestId('process-error')).not.toHaveTextContent('ElevenLabs');
    });

    it('handles polling onError callback', () => {
        render(<DashboardPage />);

        act(() => {
            capturedPollingCallbacks!.onError('Network error');
        });

        // Component should update without errors
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
    });

    it('opens account modal and closes via backdrop click', () => {
        render(<DashboardPage />);

        // Open account panel
        fireEvent.click(screen.getByLabelText('profileLabel'));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();

        // Click backdrop (the absolute inset-0 div)
        const backdrop = screen.getByTestId('account-view').closest('.fixed')?.querySelector('.absolute.inset-0');
        if (backdrop) {
            fireEvent.click(backdrop);
        }

        // Modal should close
        expect(screen.queryByTestId('account-view')).not.toBeInTheDocument();
    });
});
