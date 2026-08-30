import { render, screen, waitFor } from "@testing-library/react";
import ObservabilityAdminPage from "@/app/admin/observability/page";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { fetchObservabilitySnapshot } from "@/lib/observability";

jest.mock("@/context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("@/context/I18nContext", () => ({ useI18n: jest.fn() }));
jest.mock("@/lib/observability", () => ({
  fetchObservabilitySnapshot: jest.fn(),
}));
jest.mock("@/components/BrandLogo", () => ({
  BrandLogo: () => <span>GSUBS</span>,
}));

const snapshot = {
  generated_at: 1_788_048_000,
  retention_hours: 168,
  active: {
    authenticated_accounts: 2,
    guest_browser_sessions: 3,
    estimated_total: 5,
    window_seconds: 90,
  },
  totals: { api_error: 1, backend_error: 2 },
  jobs: { completed: 7, failed: 1 },
  actions: [
    {
      name: "export_completed",
      outcome: "succeeded",
      export_format: "1080p",
      count: 4,
    },
  ],
  errors: [
    {
      kind: "api_error",
      name: "http_5xx",
      route: "studio",
      status_code: 503,
      count: 1,
    },
  ],
  recent: [
    {
      ts: 1_788_048_000,
      kind: "action",
      name: "export_completed",
      route: "studio",
      auth_state: "authenticated",
    },
  ],
};

describe("ObservabilityAdminPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useAuth as jest.Mock).mockReturnValue({
      user: { id: "owner" },
      isLoading: false,
    });
    (useI18n as jest.Mock).mockReturnValue({
      locale: "en",
      t: (key: string) => key,
    });
    (fetchObservabilitySnapshot as jest.Mock).mockResolvedValue(snapshot);
  });

  it("renders live counts, actions, jobs, and sanitized errors", async () => {
    render(<ObservabilityAdminPage />);

    await waitFor(() => expect(screen.getByText("5")).toBeInTheDocument());
    expect(
      screen.getByText(/export_completed · succeeded · 1080p/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/api_error · http_5xx · studio · 503/),
    ).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("observabilityPrivacy")).toBeInTheDocument();
  });

  it("fails closed for a non-allowlisted account", async () => {
    (fetchObservabilitySnapshot as jest.Mock).mockRejectedValue(
      new Error("observability_snapshot_403"),
    );
    render(<ObservabilityAdminPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "observabilityForbidden",
    );
  });
});
