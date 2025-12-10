/**
 * Regression coverage for the dashboard UI tabs and data rendering.
 */
import { render, screen, fireEvent, waitForElementToBeRemoved } from '@testing-library/react';
import DashboardPage from '@/app/page';
import { I18nProvider } from '@/context/I18nContext';

jest.mock('@/context/AuthContext', () => {
    const logoutMock = jest.fn();
    const refreshUserMock = jest.fn();
    return {
        useAuth: () => ({
            user: { id: '1', name: 'Tester', email: 't@e.com', provider: 'google' },
            isLoading: false,
            logout: logoutMock,
            refreshUser: refreshUserMock,
        }),
        __logoutMock: logoutMock,
        __refreshUserMock: refreshUserMock,
    };
});

jest.mock('next/navigation', () => ({
    useRouter: () => ({ push: jest.fn() }),
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

beforeEach(() => {
    jest.clearAllMocks();
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

    // With updated UI, we have a History tab and a History section title (Recent Jobs)
    // Detailed verification of "Recent Jobs" history section in Process view
    const recentJobsHeader = await screen.findByRole('heading', { name: /History/i });
    expect(recentJobsHeader).toBeInTheDocument();

    // The mock returns an event with "Processed demo.mp4"
    // We must await this to ensure the useJobs hook has finished its state updates
    // This fixes the "An update to DashboardPage inside a test was not wrapped in act(...)" warning
    const demoTexts = await screen.findAllByText('demo.mp4');
    expect(demoTexts.length).toBeGreaterThan(0);

    // Ensure selected job is fully loaded and displayed
    expect(await screen.findByText('Subtitles Ready')).toBeInTheDocument();

    // Wait for the loading state to finish (last state update in useJobs)
    // This ensures all state updates are processed within the test's act boundary
    const loadingIndicator = screen.queryByTestId('jobs-loading');
    if (loadingIndicator) {
        await waitForElementToBeRemoved(loadingIndicator);
    }
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
});

it('renders the language toggle in the footer', () => {
    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    // Language toggle is now in footer with flag icon, aria-label includes "Switch to"
    const toggle = screen.getByRole('button', { name: /Switch to/i });
    expect(toggle).toBeInTheDocument();
});

it('displays the subtitle model used for completed jobs', async () => {
    // Mock a completed job with specific model info
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
            output_size: 1024 * 1024 * 5, // 5MB
            resolution: '1080x1920'
        }
    };

    // Use mockResolvedValue (not Once) to ensure any re-renders or multiple calls get the same data
    getJobsMock.mockResolvedValue([mockJob]);

    render(
        <I18nProvider initialLocale="en">
            <DashboardPage />
        </I18nProvider>,
    );

    // Wait for the job to be rendered (it appears in multiple places: history list, main card header, details card)
    const filenames = await screen.findAllByText('test_video.mp4');
    expect(filenames.length).toBeGreaterThan(0);

    // Check for the model label we expect from our logic
    // "Turbo" comes from text, "Local" comes from label -> "Turbo (Local)"
    expect(await screen.findByText('Turbo')).toBeInTheDocument();
    expect(await screen.findByText('(Local)')).toBeInTheDocument();

    // Wait for the loading state to finish (last state update in useJobs)
    const loadingIndicator = screen.queryByTestId('jobs-loading');
    if (loadingIndicator) {
        await waitForElementToBeRemoved(loadingIndicator);
    }
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
});

