import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
  within,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import DashboardPage from "@/app/page";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useJobs } from "@/hooks/useJobs";

export const mockPaidCreditLegalPublication = { approved: false };

// Mocks
jest.mock("@/lib/api", () => ({
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

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@/context/PointsContext", () => ({
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

jest.mock("@/context/I18nContext", () => {
  const translate = (key: string) => key;
  return {
    useI18n: () => ({ t: translate }),
  };
});

jest.mock("@/lib/paidCreditLegal", () => ({
  paidCreditLegalPublicationIsApproved: () =>
    mockPaidCreditLegalPublication.approved,
}));

jest.mock("@/hooks/useJobs", () => ({
  useJobs: jest.fn(),
}));

export let capturedPollingCallbacks: {
  onProgress: (progress: number, message: string) => void;
  onComplete: (job: unknown) => void;
  onFailed: (error: string) => void;
  onError: (error: string) => void;
} | null = null;
export let capturedPollingJobId: string | null = null;

jest.mock("@/hooks/useJobPolling", () => ({
  useJobPolling: ({
    jobId,
    callbacks,
  }: {
    jobId: string | null;
    callbacks: typeof capturedPollingCallbacks;
  }) => {
    capturedPollingJobId = jobId;
    capturedPollingCallbacks = callbacks;
    return { isPolling: false, stopPolling: jest.fn() };
  },
}));

export let capturedOnReset: (() => void) | null = null;

jest.mock("@/features/process/ProcessView", () => ({
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
        <button
          onClick={() =>
            onFileSelect(new File(["dummy"], "test.mp4", { type: "video/mp4" }))
          }
        >
          Select File
        </button>
        <button
          onClick={() =>
            onStartProcessing({
              transcribeMode: "standard",
              transcribeProvider: "mock",
              outputQuality: "balanced",
              outputResolution: "1080x1920",
              width: 1920,
              height: 1080,
              duration: 10,
              sourceDurationSeconds: 10,
              subtitle_position: 16,
              max_subtitle_lines: 2,
              watermark_enabled: true,
            })
          }
        >
          Start Process
        </button>
        <button
          onClick={() =>
            onStartProcessing({
              transcribeMode: "standard",
              transcribeProvider: "groq",
              outputQuality: "balanced",
              outputResolution: "1080x1920",
              width: 1920,
              height: 1080,
              duration: 10,
              sourceDurationSeconds: 10,
              subtitle_position: 16,
              max_subtitle_lines: 2,
              watermark_enabled: true,
            })
          }
        >
          Start External Process
        </button>
        <button
          onClick={() =>
            onReprocessJob("job1", {
              transcribeMode: "standard",
              transcribeProvider: "groq",
              outputQuality: "balanced",
              outputResolution: "1080x1920",
              width: 1920,
              height: 1080,
              duration: 10,
              sourceDurationSeconds: 10,
              subtitle_position: 16,
              max_subtitle_lines: 2,
              watermark_enabled: true,
            })
          }
        >
          Reprocess
        </button>
        {onCancelProcessing && (
          <button onClick={onCancelProcessing}>Cancel Active Process</button>
        )}
        <button onClick={onReset}>Reset</button>
      </div>
    );
  },
}));

jest.mock("@/components/AccountView", () => ({
  AccountView: ({
    onSaveProfile,
    onLogout,
    onRefreshJobs,
    accountError,
  }: {
    onSaveProfile: (name: string, pass1: string, pass2: string) => void;
    onLogout: () => Promise<void>;
    onRefreshJobs?: () => void | Promise<void>;
    accountError?: string;
  }) => (
    <div data-testid="account-view">
      <button
        data-testid="save-profile-btn"
        onClick={() => onSaveProfile("NewName", "pass", "pass")}
      >
        Save Profile
      </button>
      <button
        data-testid="save-mismatch-btn"
        onClick={() => onSaveProfile("Test User", "pass", "different")}
      >
        Save Mismatch
      </button>
      <button
        data-testid="save-name-only-btn"
        onClick={() => onSaveProfile("NewName", "", "")}
      >
        Save Name Only
      </button>
      <button type="button" onClick={() => void onLogout()}>
        Sign out
      </button>
      {accountError && <p>{accountError}</p>}
      <button data-testid="refresh-jobs-btn" onClick={() => onRefreshJobs?.()}>
        Refresh Jobs
      </button>
    </div>
  ),
}));

export {
  DashboardPage,
  api,
  useAuth,
  useJobs,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
};

export const mockUser = {
  id: "1",
  name: "Test User",
  email: "test@example.com",
  provider: "local",
};
export const mockLoadJobs = jest.fn();
export const mockRefreshUser = jest.fn();
export const mockRetrySession = jest.fn();
export const mockLogin = jest.fn();
export const mockRegister = jest.fn();
export const mockDismissBetaCreditsAwarded = jest.fn();
export const mockSetSelectedJob = jest.fn();
const pointsContextMock = jest.requireMock("@/context/PointsContext") as {
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
export const __setBalanceMock = pointsContextMock.__setBalanceMock;
export const __setWalletMock = pointsContextMock.__setWalletMock;
export const __refreshBalanceMock = pointsContextMock.__refreshBalanceMock;
export const __setPointsStateMock = pointsContextMock.__setPointsStateMock;
const __resetPointsStateMock = pointsContextMock.__resetPointsStateMock;

export function installDashboardTestEnvironment() {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
    capturedOnReset = null;
    capturedPollingCallbacks = null;
    capturedPollingJobId = null;
    mockPaidCreditLegalPublication.approved = false;
    __resetPointsStateMock();
    (useAuth as jest.Mock).mockReturnValue({
      user: mockUser,
      isLoading: false,
      sessionUnavailable: false,
      betaCreditsAwarded: 0,
      refreshUser: mockRefreshUser,
      retrySession: mockRetrySession,
      logout: jest.fn(),
      login: mockLogin,
      register: mockRegister,
      dismissBetaCreditsAwarded: mockDismissBetaCreditsAwarded,
    });
    (api.getPointsBalance as jest.Mock).mockResolvedValue({ balance: 125 });
    (api.getCreditCatalog as jest.Mock).mockResolvedValue({
      catalog_version: "video-credits-v1",
      currency: "eur",
      billing_country_scope: ["GR"],
      checkout_enabled: false,
      consumer_contract_status: "unavailable_unapproved",
      consumer_contract: null,
      packages: [
        {
          key: "starter",
          credits: 100,
          amount_eur_cents: 100,
          featured: false,
        },
      ],
      video_pricing: [
        { key: "up_to_3m", max_duration_seconds: 180, credits: 30 },
        { key: "up_to_6m", max_duration_seconds: 360, credits: 60 },
        { key: "up_to_10m", max_duration_seconds: 600, credits: 100 },
      ],
    });
    (useJobs as jest.Mock).mockReturnValue({
      selectedJob: null,
      setSelectedJob: mockSetSelectedJob,
      recentJobs: [],
      jobsLoading: false,
      jobsError: "",
      loadJobs: mockLoadJobs,
    });
  });

  afterEach(() => {
    jest.useRealTimers();
  });
}

export async function confirmProcessingCost() {
  const dialog = await screen.findByRole("dialog", {
    name: "processingGateCostTitle",
  });
  const confirmButton = within(dialog).getByRole("button", {
    name: "processingGateConfirm",
  });
  await waitFor(() => expect(confirmButton).toBeEnabled());
  await act(async () => {
    fireEvent.click(confirmButton);
    await Promise.resolve();
  });
}
