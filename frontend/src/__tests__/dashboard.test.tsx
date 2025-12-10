
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

jest.mock('@/hooks/useJobs', () => ({
    useJobs: jest.fn(),
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

import { useJobs } from '@/hooks/useJobs';

describe('DashboardPage', () => {
    const mockUser = { id: '1', name: 'Test User', email: 'test@example.com' };
    const mockLoadJobs = jest.fn();

    beforeEach(() => {
        jest.clearAllMocks();
        (useAuth as jest.Mock).mockReturnValue({
            user: mockUser,
            isLoading: false,
            refreshUser: jest.fn(),
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
        // Ensure timers are restored if a test used them
        jest.useRealTimers();
    });

    it('renders dashboard components', () => {
        render(<DashboardPage />);

        expect(screen.getByText('brandName')).toBeInTheDocument();
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
        // Profile button should be visible (part of nav)
        expect(screen.getByLabelText('accountSettingsTitle')).toBeInTheDocument();
        expect(mockLoadJobs).toHaveBeenCalled();
    });

    it('opens account settings modal', () => {
        render(<DashboardPage />);

        // ProcessView should be visible
        expect(screen.getByTestId('process-view')).toBeInTheDocument();
        expect(screen.queryByTestId('account-view')).not.toBeInTheDocument();

        // Click profile button to open account settings
        fireEvent.click(screen.getByLabelText('accountSettingsTitle'));
        expect(screen.getByTestId('account-view')).toBeInTheDocument();

        // Click close button
        fireEvent.click(screen.getByText('✕'));
        expect(screen.queryByTestId('account-view')).not.toBeInTheDocument();
    });
});
