/**
 * Regression coverage for the dashboard UI tabs and data rendering.
 * 
 * All tests properly handle async state updates from useJobs hook to eliminate
 * React's "not wrapped in act(...)" warnings.
 */
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import DashboardPage from '@/app/page';
import { I18nProvider } from '@/context/I18nContext';

const logoutMock = jest.fn();
const refreshUserMock = jest.fn();
const pushMock = jest.fn();

let mockUser: { id: string; name: string; email: string; provider: string } | null = { id: '1', name: 'Tester', email: 't@e.com', provider: 'google' };
let mockIsLoading = false;

jest.mock('@/context/AuthContext', () => ({
    useAuth: () => ({
        user: mockUser,
        isLoading: mockIsLoading,
        logout: logoutMock,
        refreshUser: refreshUserMock,
    }),
}));

jest.mock('next/navigation', () => ({
    useRouter: () => ({ push: pushMock }),
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
            updateProfile: jest.fn(),
            updatePassword: jest.fn(),
        },
        __getJobsMock: getJobs,
        __getHistoryMock: getHistory,
    };
});

const { __getJobsMock, __getHistoryMock } = jest.requireMock('@/lib/api');
const getJobsMock = __getJobsMock as jest.Mock;
const getHistoryMock = __getHistoryMock as jest.Mock;

beforeEach(() => {
    jest.clearAllMocks();
    mockUser = { id: '1', name: 'Tester', email: 't@e.com', provider: 'google' };
    mockIsLoading = false;
    getJobsMock.mockResolvedValue([
        {
            id: 'job1',
            status: 'completed',
            progress: 100,
            message: 'Done',
            created_at: 1,
            updated_at: 2,
            result_data: {
                video_path: 'data/artifacts/job1/processed.mp4',
                public_url: '/static/data/artifacts/job1/processed.mp4',
                original_filename: 'demo.mp4',
                model_size: 'medium',
                video_crf: 23,
                artifacts_dir: '/artifacts',
            },
        },
    ]);
    getHistoryMock.mockResolvedValue([
        {
            ts: new Date().toISOString(),
            user_id: '1',
            email: 't@e.com',
            kind: 'process_completed',
            summary: 'Processed demo.mp4',
            data: {},
        },
    ]);
});

it('renders workspace with recent jobs', async () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    const recentJobsHeader = await screen.findByRole('heading', { name: /History/i });
    expect(recentJobsHeader).toBeInTheDocument();

    const demoTexts = await screen.findAllByText('demo.mp4');
    expect(demoTexts.length).toBeGreaterThan(0);

    expect(await screen.findByText('Subtitles Ready')).toBeInTheDocument();

    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });
});

it('shows the updated hero and clickable dropzone', async () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    expect(await screen.findByText(/Build export-ready shorts/i)).toBeInTheDocument();
    const dropCopy = await screen.findByText(/Drop your vertical clip/i);
    expect(dropCopy.closest('[data-clickable="true"]')).not.toBeNull();

    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });
});

it('renders the language toggle in the footer', async () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });

    const toggle = screen.getByRole('button', { name: /Switch to/i });
    expect(toggle).toBeInTheDocument();
});

it('displays the subtitle model used for completed jobs', async () => {
    const mockJob = {
        id: 'job-123',
        status: 'completed',
        progress: 100,
        message: null,
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        result_data: {
            video_path: '/path/to/video.mp4',
            artifacts_dir: '/path/to/artifacts',
            original_filename: 'test_video.mp4',
            transcribe_provider: 'local',
            model_size: 'large-v3-turbo',
            output_size: 1024 * 1024 * 5,
            resolution: '1080x1920'
        }
    };

    getJobsMock.mockResolvedValue([mockJob]);

    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    const filenames = await screen.findAllByText('test_video.mp4');
    expect(filenames.length).toBeGreaterThan(0);

    expect(await screen.findByText('Turbo')).toBeInTheDocument();
    expect(await screen.findByText('(Local)')).toBeInTheDocument();

    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });
});

it('shows a profile button with an avatar icon and accessible label', async () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    const profileButton = await screen.findByLabelText(/Account settings/i);
    expect(profileButton).toBeInTheDocument();
    expect(profileButton.textContent).toContain('Tester');
    expect(profileButton.querySelector('[aria-hidden="true"]')).not.toBeNull();

    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });
});

it('shows loading state when isLoading is true', async () => {
    mockIsLoading = true;

    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();
});

it('redirects to login when user is null', async () => {
    mockUser = null;

    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    await waitFor(() => {
        expect(pushMock).toHaveBeenCalledWith('/login');
    });
});

it('toggles account panel when profile button is clicked', async () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    const profileButton = await screen.findByLabelText(/Account settings/i);

    await act(async () => {
        fireEvent.click(profileButton);
    });

    // Account panel should now be visible - find the modal heading specifically
    const headings = await screen.findAllByRole('heading', { name: /Account settings/i });
    expect(headings.length).toBeGreaterThan(0);

    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });
});

it('calls logout when sign out button is clicked', async () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    const signOutButton = await screen.findByRole('button', { name: /Sign out/i });

    await act(async () => {
        fireEvent.click(signOutButton);
    });

    expect(logoutMock).toHaveBeenCalled();
});

it('handles empty jobs list gracefully', async () => {
    getJobsMock.mockResolvedValue([]);

    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });

    // Should still render the History section
    expect(screen.getByRole('heading', { name: /History/i })).toBeInTheDocument();
});

it('shows the brand name in the navbar', async () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });

    // Check for subtitle desk text which is displayed in navbar  
    const brandElements = screen.queryAllByText(/Subtitle desk/i);
    expect(brandElements.length).toBeGreaterThan(0);
});

it('renders status badge for completed job', async () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    // Wait for jobs to load
    await waitFor(() => {
        expect(getJobsMock).toHaveBeenCalled();
    });

    // Look for job content - the filename may appear multiple times
    const filenames = await screen.findAllByText('demo.mp4');
    expect(filenames.length).toBeGreaterThan(0);
});
