import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardPage from '@/app/page';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { useJobs } from '@/hooks/useJobs';
import { useAppEnv } from '@/context/AppEnvContext';

// Mocks
jest.mock('@/lib/api', () => ({
    api: {
        getJobs: jest.fn(),
        getHistory: jest.fn(),
        getJobStatus: jest.fn(),
        processVideo: jest.fn(),
        createGcsUploadUrl: jest.fn(),
        uploadToSignedUrl: jest.fn(),
        processVideoFromGcs: jest.fn(),
        reprocessJob: jest.fn(),
        getPointsBalance: jest.fn(),
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
        const refreshBalanceMock = jest.fn();
        return {
            usePoints: () => ({
                balance: 125,
                isLoading: false,
                error: null,
                setBalance: setBalanceMock,
                refreshBalance: refreshBalanceMock,
            }),
            __setBalanceMock: setBalanceMock,
            __refreshBalanceMock: refreshBalanceMock,
        };
    })(),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('@/context/AppEnvContext', () => ({
    useAppEnv: jest.fn(),
}));

jest.mock('@/hooks/useJobs', () => ({
    useJobs: jest.fn(),
}));

let capturedPollingCallbacks: { onProgress: (progress: number, message: string) => void; onComplete: (job: unknown) => void; onFailed: (error: string) => void; onError: (error: string) => void; } | null = null;

jest.mock('@/hooks/useJobPolling', () => ({
    useJobPolling: ({ callbacks }: { callbacks: typeof capturedPollingCallbacks }) => {
        capturedPollingCallbacks = callbacks;
        return { isPolling: false, stopPolling: jest.fn() };
    },
}));

let capturedOnReset: (() => void) | null = null;

jest.mock('@/features/process/ProcessView', () => ({
    ProcessView: ({ onStartProcessing, onFileSelect, onReset, onReprocessJob }: { onStartProcessing: (options: unknown) => void; onFileSelect: (file: File) => void; onReset: () => void; onReprocessJob: (jobId: string, options: unknown) => void; }) => {
        capturedOnReset = onReset;
        return (
            <div data-testid="process-view">
                <button onClick={() => onFileSelect(new File(['dummy'], 'test.mp4', { type: 'video/mp4' }))}>Select File</button>
                <button onClick={() => onStartProcessing({
                    transcribeMode: 'standard',
                    transcribeProvider: 'mock',
                    outputQuality: 'balanced',
                    outputResolution: '1080x1920',
                    width: 1920,
                    height: 1080,
                    duration: 10,
                    subtitle_position: 16,
                    max_subtitle_lines: 2,
                    watermark_enabled: true,
                })}>Start Process</button>
                <button onClick={() => onReprocessJob('job1', {
                    transcribeMode: 'standard',
                    transcribeProvider: 'groq',
                    outputQuality: 'balanced',
                    outputResolution: '1080x1920',
                    width: 1920,
                    height: 1080,
                    duration: 10,
                    subtitle_position: 16,
                    max_subtitle_lines: 2,
                    watermark_enabled: true,
                })}>Reprocess</button>
                <button onClick={onReset}>Reset</button>
            </div>
        );
    },
}));

jest.mock('@/components/AccountView', () => ({
    AccountView: ({ onSaveProfile, onRefreshJobs }: { onSaveProfile: (name: string, pass1: string, pass2: string) => void; onRefreshJobs?: () => void | Promise<void> }) => (
        <div data-testid="account-view">
            <button data-testid="save-profile-btn" onClick={() => onSaveProfile('NewName', 'pass', 'pass')}>Save Profile</button>
            <button data-testid="save-mismatch-btn" onClick={() => onSaveProfile('Test User', 'pass', 'different')}>Save Mismatch</button>
            <button data-testid="save-name-only-btn" onClick={() => onSaveProfile('NewName', '', '')}>Save Name Only</button>
            <button data-testid="refresh-jobs-btn" onClick={() => onRefreshJobs?.()}>Refresh Jobs</button>
        </div>
    ),
}));

describe('DashboardPage', () => {
    const mockUser = { id: '1', name: 'Test User', email: 'test@example.com', provider: 'local' };
    const mockLoadJobs = jest.fn();
    const mockRefreshUser = jest.fn();
    const mockLogin = jest.fn();
    const mockRegister = jest.fn();
    const mockSetSelectedJob = jest.fn();
    const { __setBalanceMock, __refreshBalanceMock } = jest.requireMock('@/context/PointsContext') as {
        __setBalanceMock: jest.Mock;
        __refreshBalanceMock: jest.Mock;
    };

    beforeEach(() => {
        jest.clearAllMocks();
        window.localStorage.clear();
        capturedOnReset = null;
        (useAppEnv as jest.Mock).mockReturnValue({ appEnv: 'dev' });
        (useAuth as jest.Mock).mockReturnValue({
            user: mockUser,
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout: jest.fn(),
            login: mockLogin,
            register: mockRegister,
        });
        (api.getPointsBalance as jest.Mock).mockResolvedValue({ balance: 125 });
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
        expect(mockLoadJobs).not.toHaveBeenCalled();
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

    it('renders the precision header and opens history from its navigation', () => {
        render(<DashboardPage />);

        const studioHeader = screen.getByRole('banner', { name: 'Subframe studio' });
        expect(studioHeader).toBeInTheDocument();
        expect(screen.getByRole('navigation', { name: 'Workspace navigation' })).toBeInTheDocument();
        expect(screen.getByTestId('studio-intro')).toHaveClass('studio-intro');
        expect(screen.getByTestId('studio-header-credits')).toBeInTheDocument();
        expect(screen.getByTestId('credits-coin-icon')).toBeInTheDocument();
        expect(screen.getByTestId('credits-balance')).toHaveTextContent('125');
        expect(studioHeader).not.toHaveTextContent('Mock');
        expect(studioHeader).not.toHaveTextContent('€0');
        expect(screen.queryByText('accountSettingsTitle')).not.toBeInTheDocument();
        expect(screen.queryByText('2026 REMAKE')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'switchLanguage' })).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'historyTitle' }));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();
        expect(studioHeader).toHaveAttribute('aria-hidden', 'true');
        expect(studioHeader).toHaveAttribute('inert');
        expect(screen.queryByRole('button', { name: 'switchLanguage' })).not.toBeInTheDocument();
    });

    it('opens account settings only from the profile avatar', () => {
        render(<DashboardPage />);

        expect(screen.queryByText('accountSettingsTitle')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'profileLabel' }));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();
    });

    it('renders footer with privacy and terms links', () => {
        render(<DashboardPage />);

        const privacyLink = screen.getByText('cookieLearnMore');
        const termsLink = screen.getByText('cookieTerms');

        expect(privacyLink).toBeInTheDocument();
        expect(privacyLink.closest('a')).toHaveAttribute('href', '/privacy');

        expect(termsLink).toBeInTheDocument();
        expect(termsLink.closest('a')).toHaveAttribute('href', '/terms');
    });

    it('shows loading state when isLoading is true', () => {
        (useAuth as jest.Mock).mockReturnValue({
            user: null,
            isLoading: true,
            refreshUser: mockRefreshUser,
            logout: jest.fn(),
        });

        render(<DashboardPage />);
        expect(screen.getByText('loading')).toBeInTheDocument();
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
        expect(screen.getByRole('button', { name: 'guestSignIn' })).toBeInTheDocument();
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

        await waitFor(() => expect(api.processVideo).toHaveBeenCalledWith(expect.any(File), expect.any(Object)));
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
                watermark_enabled: true,
            }),
        );
        expect(__setBalanceMock).toHaveBeenCalledWith(800);
    });

    it('keeps production mock uploads on the local processing endpoint', async () => {
        (useAppEnv as jest.Mock).mockReturnValue({ appEnv: 'production' });
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalledWith(
                expect.any(File),
                expect.objectContaining({ transcribe_provider: 'mock' }),
            );
        });
        expect(api.createGcsUploadUrl).not.toHaveBeenCalled();
        expect(api.uploadToSignedUrl).not.toHaveBeenCalled();
        expect(api.processVideoFromGcs).not.toHaveBeenCalled();
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
        (api.processVideo as jest.Mock).mockRejectedValue(new Error('Processing failed'));
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });
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
        render(<DashboardPage />);

        // Trigger reset via captured callback
        fireEvent.click(screen.getByText('Reset'));

        // Test verifies the code path is executed without errors
        expect(capturedOnReset).toBeDefined();

        // REGRESSION: Verify that setSelectedJob(null) is called to clear previous job
        expect(mockSetSelectedJob).toHaveBeenCalledWith(null);
    });

    it.skip('handles job polling with completion', async () => {
        jest.useFakeTimers();
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        (api.getJobStatus as jest.Mock)
            .mockResolvedValueOnce({ id: 'job123', status: 'processing', progress: 50, message: 'Processing' })
            .mockResolvedValueOnce({ id: 'job123', status: 'completed', progress: 100, result_data: { public_url: 'test' } });

        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });

        // Advance timers and flush promises
        await act(async () => {
            jest.advanceTimersByTime(1100);
        });

        await waitFor(() => {
            expect(api.getJobStatus).toHaveBeenCalledWith('job123');
        });

        // Second poll for completion
        await act(async () => {
            jest.advanceTimersByTime(1100);
        });

        await waitFor(() => {
            expect(api.getJobStatus).toHaveBeenCalledTimes(2);
        });

        jest.useRealTimers();
    });

    it.skip('handles job polling with failure', async () => {
        jest.useFakeTimers();
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        (api.getJobStatus as jest.Mock).mockResolvedValue({ id: 'job123', status: 'failed', message: 'Job failed' });

        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });

        await act(async () => {
            jest.advanceTimersByTime(1100);
        });

        await waitFor(() => {
            expect(api.getJobStatus).toHaveBeenCalledWith('job123');
        });

        jest.useRealTimers();
    });

    it.skip('handles job polling error', async () => {
        jest.useFakeTimers();
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        (api.getJobStatus as jest.Mock).mockRejectedValue(new Error('Network error'));

        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));
        await confirmProcessingCost();

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });

        await act(async () => {
            jest.advanceTimersByTime(1100);
            await Promise.resolve();
        });

        jest.useRealTimers();
    });

    it.skip('opens and closes account modal', () => {
        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('profileLabel'));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();

        // Click the actual modal close button (the ✕ in the modal header from page.tsx)
        const closeButton = screen.getByRole('button', { name: '' });
        fireEvent.click(closeButton);
        expect(screen.queryByTestId('account-view')).not.toBeInTheDocument();
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
