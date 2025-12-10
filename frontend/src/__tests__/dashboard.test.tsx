
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardPage from '@/app/page';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

// Mocks
jest.mock('@/lib/api', () => ({
    api: {
        getJobs: jest.fn(),
        getHistory: jest.fn(),
        getJobStatus: jest.fn(),
    },
}));

jest.mock('@/context/AuthContext', () => ({
    useAuth: jest.fn(),
}));

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('@/components/AccountView', () => ({
    AccountView: () => <div data-testid="account-view">AccountView</div>,
}));

jest.mock('@/components/ProcessView', () => ({
    ProcessView: ({ onRefreshJobs }: any) => (
        <div data-testid="process-view">
            <button onClick={onRefreshJobs}>Refresh Jobs</button>
        </div>
    ),
}));

describe('DashboardPage', () => {
    const mockUser = { id: '1', name: 'Test User', email: 'test@example.com' };

    beforeEach(() => {
        jest.clearAllMocks();
        (useAuth as jest.Mock).mockReturnValue({
            user: mockUser,
            isLoading: false,
            refreshUser: jest.fn(),
        });
        (api.getJobs as jest.Mock).mockResolvedValue([]);
        (api.getHistory as jest.Mock).mockResolvedValue([]);
    });

    it('renders dashboard components', async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        expect(screen.getByText('appName')).toBeInTheDocument();
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
        // Tabs should be visible
        expect(screen.getByText('navWorkspace')).toBeInTheDocument();
        expect(screen.getByText('navAccount')).toBeInTheDocument();
    });

    it('navigates between tabs', async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        // Default is workspace
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
        expect(screen.queryByTestId('account-view')).not.toBeInTheDocument();

        // Switch to account
        fireEvent.click(screen.getByText('navAccount'));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();
        expect(screen.queryByTestId('process-view')).not.toBeInTheDocument();

        // Switch back
        fireEvent.click(screen.getByText('navWorkspace'));
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
    });

    it('handles polling for job status', async () => {
        jest.useFakeTimers();
        (api.getJobs as jest.Mock).mockResolvedValue([{ id: 'job1', status: 'pending' }]);
        (api.getJobStatus as jest.Mock).mockResolvedValue({ id: 'job1', status: 'completed' });

        await act(async () => {
            render(<DashboardPage />);
        });

        // Should poll
        await act(async () => {
            jest.advanceTimersByTime(3000);
        });

        expect(api.getJobs).toHaveBeenCalled();
        jest.useRealTimers();
    });
});
