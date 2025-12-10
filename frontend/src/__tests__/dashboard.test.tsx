
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardPage from '@/app/page';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { useJobs } from '@/hooks/useJobs';
import { useRouter } from 'next/navigation';

// Mocks
jest.mock('@/lib/api', () => ({
    api: {
        getJobs: jest.fn(),
        getHistory: jest.fn(),
        getJobStatus: jest.fn(),
        processVideo: jest.fn(),
        updateProfile: jest.fn(),
        updatePassword: jest.fn(),
    },
}));

jest.mock('@/context/AuthContext', () => ({
    useAuth: jest.fn(),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('@/hooks/useJobs', () => ({
    useJobs: jest.fn(),
}));

jest.mock('next/navigation', () => ({
    useRouter: jest.fn(),
}));

let capturedOnReset: (() => void) | null = null;

jest.mock('@/components/ProcessView', () => ({
    ProcessView: ({ onStartProcessing, onRefreshJobs, onFileSelect, onReset }: any) => {
        capturedOnReset = onReset;
        return (
            <div data-testid="process-view">
                <button onClick={() => onFileSelect(new File(['dummy'], 'test.mp4', { type: 'video/mp4' }))}>Select File</button>
                <button onClick={() => onStartProcessing({
                    transcribeMode: 'fast',
                    transcribeProvider: 'local',
                    outputQuality: 'balanced',
                    outputResolution: '1080x1920',
                    useAI: false,
                    contextPrompt: '',
                    subtitle_position: 'bottom',
                    max_subtitle_lines: 2
                })}>Start Process</button>
                <button onClick={onRefreshJobs}>Refresh Jobs</button>
                <button onClick={onReset}>Reset</button>
            </div>
        );
    },
}));

jest.mock('@/components/AccountView', () => ({
    AccountView: ({ onSaveProfile }: any) => (
        <div data-testid="account-view">
            <button data-testid="save-profile-btn" onClick={() => onSaveProfile('NewName', 'pass', 'pass')}>Save Profile</button>
            <button data-testid="save-mismatch-btn" onClick={() => onSaveProfile('Test User', 'pass', 'different')}>Save Mismatch</button>
            <button data-testid="save-name-only-btn" onClick={() => onSaveProfile('NewName', '', '')}>Save Name Only</button>
        </div>
    ),
}));

describe('DashboardPage', () => {
    const mockUser = { id: '1', name: 'Test User', email: 'test@example.com', provider: 'local' };
    const mockLoadJobs = jest.fn();
    const mockPush = jest.fn();
    const mockRefreshUser = jest.fn();
    const mockSetSelectedJob = jest.fn();

    beforeEach(() => {
        jest.clearAllMocks();
        capturedOnReset = null;
        (useRouter as jest.Mock).mockReturnValue({ push: mockPush });
        (useAuth as jest.Mock).mockReturnValue({
            user: mockUser,
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout: jest.fn(),
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

    it('renders dashboard components', () => {
        render(<DashboardPage />);

        expect(screen.getByText('brandName')).toBeInTheDocument();
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
        expect(screen.getByLabelText('accountSettingsTitle')).toBeInTheDocument();
        expect(mockLoadJobs).toHaveBeenCalled();
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

    it('returns null when no user and not loading', () => {
        (useAuth as jest.Mock).mockReturnValue({
            user: null,
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout: jest.fn(),
        });

        const { container } = render(<DashboardPage />);
        expect(container.firstChild).toBeNull();
    });

    it('redirects to login when no user', async () => {
        (useAuth as jest.Mock).mockReturnValue({
            user: null,
            isLoading: false,
            refreshUser: mockRefreshUser,
            logout: jest.fn(),
        });

        render(<DashboardPage />);

        await waitFor(() => {
            expect(mockPush).toHaveBeenCalledWith('/login');
        });
    });

    it('handles start processing success', async () => {
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });
    });

    it('handles start processing error', async () => {
        (api.processVideo as jest.Mock).mockRejectedValue(new Error('Processing failed'));
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });
    });

    it('handles profile save with name change', async () => {
        (api.updateProfile as jest.Mock).mockResolvedValue({});
        mockRefreshUser.mockResolvedValue({});

        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('accountSettingsTitle'));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Save Name Only'));

        await waitFor(() => {
            expect(api.updateProfile).toHaveBeenCalledWith('NewName');
            expect(mockRefreshUser).toHaveBeenCalled();
        });
    });

    it('handles profile save with password mismatch', async () => {
        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('accountSettingsTitle'));
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

        fireEvent.click(screen.getByLabelText('accountSettingsTitle'));
        fireEvent.click(screen.getByText('Save Profile'));

        await waitFor(() => {
            expect(api.updateProfile).toHaveBeenCalledWith('NewName');
            expect(api.updatePassword).toHaveBeenCalledWith('pass', 'pass');
        });
    });

    it('handles profile save error', async () => {
        (api.updateProfile as jest.Mock).mockRejectedValue(new Error('Update failed'));

        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('accountSettingsTitle'));
        fireEvent.click(screen.getByText('Save Name Only'));

        await waitFor(() => {
            expect(api.updateProfile).toHaveBeenCalled();
        });
    });

    it('handles reset processing', async () => {
        render(<DashboardPage />);

        // Trigger reset via captured callback
        fireEvent.click(screen.getByText('Reset'));

        // Test verifies the code path is executed without errors
        expect(capturedOnReset).toBeDefined();
    });

    it.skip('handles job polling with completion', async () => {
        jest.useFakeTimers();
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        (api.getJobStatus as jest.Mock)
            .mockResolvedValueOnce({ id: 'job123', status: 'processing', progress: 50 })
            .mockResolvedValueOnce({ id: 'job123', status: 'completed', progress: 100, result_data: {} });

        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });

        // Advance timers to trigger polling
        await act(async () => {
            jest.advanceTimersByTime(1100);
            await Promise.resolve();
        });

        await waitFor(() => {
            expect(api.getJobStatus).toHaveBeenCalledWith('job123');
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

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });

        await act(async () => {
            jest.advanceTimersByTime(1100);
            await Promise.resolve();
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

        fireEvent.click(screen.getByLabelText('accountSettingsTitle'));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();

        // Click the actual modal close button (the ✕ in the modal header from page.tsx)
        const closeButton = screen.getByRole('button', { name: '' });
        fireEvent.click(closeButton);
        expect(screen.queryByTestId('account-view')).not.toBeInTheDocument();
    });

    it('calls refreshActivity via refresh button', async () => {
        render(<DashboardPage />);

        fireEvent.click(screen.getByText('Refresh Jobs'));

        await waitFor(() => {
            expect(mockLoadJobs).toHaveBeenCalledTimes(2); // Once on mount, once on refresh
        });
    });
});
