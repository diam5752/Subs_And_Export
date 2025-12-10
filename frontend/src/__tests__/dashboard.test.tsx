
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardPage from '@/app/page';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { useJobs } from '@/hooks/useJobs';

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

jest.mock('@/components/ProcessView', () => ({
    ProcessView: ({ onStartProcessing, onRefreshJobs, onFileSelect }: any) => (
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
        </div>
    ),
}));

jest.mock('@/components/AccountView', () => ({
    AccountView: ({ onSave, onClose }: any) => (
        <div data-testid="account-view">
            <button onClick={() => onSave('NewName', 'pass', 'pass')}>Save Profile</button>
            <button onClick={onClose}>✕</button>
        </div>
    ),
}));

describe('DashboardPage', () => {
    const mockUser = { id: '1', name: 'Test User', email: 'test@example.com', provider: 'local' };
    const mockLoadJobs = jest.fn();

    beforeEach(() => {
        jest.clearAllMocks();
        (useAuth as jest.Mock).mockReturnValue({
            user: mockUser,
            isLoading: false,
            refreshUser: jest.fn(),
            logout: jest.fn(),
        });
        (useJobs as jest.Mock).mockReturnValue({
            selectedJob: null,
            setSelectedJob: jest.fn(),
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

    it.skip('opens account settings and saves profile', async () => {
        // Mock API responses for this test
        (api.updateProfile as jest.Mock).mockResolvedValue({});
        (api.updatePassword as jest.Mock).mockResolvedValue({});

        render(<DashboardPage />);

        fireEvent.click(screen.getByLabelText('accountSettingsTitle'));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Save Profile'));

        await waitFor(() => {
            expect(api.updateProfile).toHaveBeenCalledWith('NewName');
        });
        expect(api.updatePassword).toHaveBeenCalledWith('pass', 'pass');

        fireEvent.click(screen.getByText('✕'));
    });

    it('handles start processing success', async () => {
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        render(<DashboardPage />);

        // 1. Select File
        fireEvent.click(screen.getByText('Select File'));

        // 2. Start Processing
        fireEvent.click(screen.getByText('Start Process'));

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });
    });

    it.skip('polls for job status', async () => {
        jest.useFakeTimers();
        (api.processVideo as jest.Mock).mockResolvedValue({ id: 'job123', status: 'pending' });
        (api.getJobStatus as jest.Mock).mockResolvedValue({ id: 'job123', status: 'processing', progress: 50 });

        render(<DashboardPage />);

        // Start processing to set jobId
        fireEvent.click(screen.getByText('Select File'));
        fireEvent.click(screen.getByText('Start Process'));

        await waitFor(() => {
            expect(api.processVideo).toHaveBeenCalled();
        });

        // Allow promises to resolve (setJobId) - more aggressive flushing
        await act(async () => {
            await Promise.resolve();
            await Promise.resolve();
            await Promise.resolve();
        });

        // Fast-forward time to trigger poll
        await act(async () => {
            jest.advanceTimersByTime(2000);
        });

        expect(api.getJobStatus).toHaveBeenCalledWith('job123');

        // Mock completion
        (api.getJobStatus as jest.Mock).mockResolvedValue({ id: 'job123', status: 'completed', progress: 100, result_data: {} });

        await act(async () => {
            jest.advanceTimersByTime(1100);
        });

        await waitFor(() => {
            expect(mockLoadJobs).toHaveBeenCalled();
        });

        jest.useRealTimers();
    });
});
