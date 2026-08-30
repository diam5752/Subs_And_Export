import React from "react";
import {
  __refreshBalanceMock,
  api,
  capturedPollingJobId,
  confirmProcessingCost,
  DashboardPage,
  fireEvent,
  installDashboardTestEnvironment,
  mockDismissBetaCreditsAwarded,
  mockLoadJobs,
  mockLogin,
  mockPaidCreditLegalPublication,
  mockRefreshUser,
  mockRegister,
  mockRetrySession,
  mockSetSelectedJob,
  mockUser,
  render,
  screen,
  useAuth,
  useJobs,
  waitFor,
  within,
} from "../../test-support/dashboardTestSupport";
import "@testing-library/jest-dom";

describe("DashboardPage shell and account", () => {
  installDashboardTestEnvironment();

  it("renders dashboard components", () => {
    render(<DashboardPage />);

    expect(screen.getByText("heroTitle")).toBeInTheDocument();
    expect(screen.getByTestId("process-view")).toBeInTheDocument();
    expect(screen.getByLabelText("profileLabel")).toBeInTheDocument();
    expect(screen.getByTestId("beta-badge")).toHaveTextContent("betaBadge");
    expect(screen.getByText("betaTestingNotice")).toBeInTheDocument();
    expect(mockLoadJobs).not.toHaveBeenCalled();
  });

  it("shows and dismisses the first-20 credit award after an eligible login", () => {
    (useAuth as jest.Mock).mockReturnValue({
      user: mockUser,
      isLoading: false,
      sessionUnavailable: false,
      betaCreditsAwarded: 30,
      refreshUser: mockRefreshUser,
      retrySession: mockRetrySession,
      logout: jest.fn(),
      login: mockLogin,
      register: mockRegister,
      dismissBetaCreditsAwarded: mockDismissBetaCreditsAwarded,
    });

    render(<DashboardPage />);

    expect(screen.getByTestId("beta-launch-credit-award")).toHaveTextContent(
      "betaLaunchAwardTitle",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "betaLaunchAwardDismiss" }),
    );
    expect(mockDismissBetaCreditsAwarded).toHaveBeenCalledTimes(1);
  });

  it("renders the Google profile picture with an initial fallback", () => {
    // REGRESSION: authenticated Google users only saw their initial even
    // though Google provided a verified profile picture.
    (useAuth as jest.Mock).mockReturnValue({
      user: {
        ...mockUser,
        provider: "google",
        avatar_url: "https://lh3.googleusercontent.com/a/avatar=s96-c",
      },
      isLoading: false,
      refreshUser: mockRefreshUser,
      logout: jest.fn(),
      login: mockLogin,
      register: mockRegister,
    });

    render(<DashboardPage />);

    const profileButton = screen.getByRole("button", { name: "profileLabel" });
    const avatar = within(profileButton).getByTestId("profile-avatar-image");
    expect(avatar).toHaveAttribute(
      "src",
      "https://lh3.googleusercontent.com/a/avatar=s96-c",
    );
    expect(avatar).toHaveAttribute("referrerpolicy", "no-referrer");

    fireEvent.error(avatar);

    expect(
      within(profileButton).queryByTestId("profile-avatar-image"),
    ).not.toBeInTheDocument();
    expect(profileButton).toHaveTextContent("T");
  });

  it("does not restore a completed job whose preview artifacts are missing", async () => {
    window.localStorage.setItem("lastActiveJobId", "missing-job");
    (api.getJobStatus as jest.Mock).mockResolvedValue({
      id: "missing-job",
      status: "completed",
      result_data: {
        video_path: "missing.mp4",
        files_missing: true,
      },
    });

    render(<DashboardPage />);

    await waitFor(() => {
      expect(api.getJobStatus).toHaveBeenCalledWith("missing-job");
    });
    expect(mockSetSelectedJob).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("lastActiveJobId")).toBeNull();
  });

  it.each([
    ["pending", true],
    ["processing", true],
    ["cancelling", false],
  ])(
    "restores a %s job as active and resumes polling",
    async (status, isCancellable) => {
      // REGRESSION: restoring an active job only selected the stale job
      // snapshot, leaving jobId null so polling never resumed.
      window.localStorage.setItem("lastActiveJobId", "active-job");
      (api.getJobStatus as jest.Mock).mockResolvedValue({
        id: "active-job",
        status,
        progress: 42,
        message: "Still working",
        result_data: null,
      });

      render(<DashboardPage />);

      await waitFor(() => {
        expect(capturedPollingJobId).toBe("active-job");
        expect(screen.getByTestId("process-processing")).toHaveTextContent(
          "true",
        );
      });
      expect(mockSetSelectedJob).not.toHaveBeenCalled();
      if (isCancellable) {
        expect(screen.getByText("Cancel Active Process")).toBeInTheDocument();
      } else {
        expect(
          screen.queryByText("Cancel Active Process"),
        ).not.toBeInTheDocument();
        expect(screen.getByTestId("process-status")).toHaveTextContent(
          "cancellationRequested",
        );
      }
    },
  );

  it("keeps history out of the header and opens it from the profile panel", async () => {
    render(<DashboardPage />);

    const studioHeader = screen.getByRole("banner", { name: "gsubs studio" });
    expect(studioHeader).toBeInTheDocument();
    // REGRESSION: The owner-selected stacked logo was replaced by a
    // horizontal compact-split pill.
    expect(
      within(studioHeader).getByRole("img", { name: "gsubs" }),
    ).toHaveAttribute("src", "/brand/gsubs-logo.svg");
    expect(
      screen.queryByRole("navigation", { name: "Workspace navigation" }),
    ).not.toBeInTheDocument();
    expect(
      within(studioHeader).queryByRole("button", { name: "historyTitle" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("studio-intro")).toHaveClass("studio-intro");
    expect(screen.getByTestId("studio-header-credits")).toBeInTheDocument();
    expect(screen.getByTestId("credits-coin-icon")).toBeInTheDocument();
    expect(screen.getByTestId("credits-balance")).toHaveTextContent("125");
    expect(studioHeader).not.toHaveTextContent("Mock");
    expect(studioHeader).not.toHaveTextContent("€0");
    expect(screen.queryByText("accountSettingsTitle")).not.toBeInTheDocument();
    expect(screen.queryByText("2026 REMAKE")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "switchLanguage" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "profileLabel" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "historyTitle" }),
    );
    expect(screen.getByTestId("account-view")).toBeInTheDocument();
    expect(studioHeader).toHaveAttribute("aria-hidden", "true");
    expect(studioHeader).toHaveAttribute("inert");
    expect(
      screen.queryByRole("button", { name: "switchLanguage" }),
    ).not.toBeInTheDocument();
  });

  it("asks before the logo closes an active workspace and only leaves after confirmation", () => {
    // REGRESSION: the brand link navigated immediately even while a completed
    // project was open, without giving the user a chance to keep editing.
    window.localStorage.setItem("lastActiveJobId", "job-open-in-editor");
    (useJobs as jest.Mock).mockReturnValue({
      selectedJob: {
        id: "job-open-in-editor",
        status: "completed",
        result_data: { video_path: "processed.mp4" },
      },
      setSelectedJob: mockSetSelectedJob,
      recentJobs: [],
      jobsLoading: false,
      jobsError: "",
      loadJobs: mockLoadJobs,
    });
    window.scrollTo = jest.fn();

    render(<DashboardPage />);

    const homeLink = screen.getByRole("link", { name: "brandHomeLabel" });
    fireEvent.click(homeLink);

    expect(
      screen.getByRole("dialog", { name: "homeNavigationModalTitle" }),
    ).toBeInTheDocument();
    expect(mockSetSelectedJob).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("lastActiveJobId")).toBe(
      "job-open-in-editor",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "homeNavigationCancel" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "homeNavigationModalTitle" }),
    ).not.toBeInTheDocument();
    expect(mockSetSelectedJob).not.toHaveBeenCalled();

    fireEvent.click(homeLink);
    fireEvent.click(
      screen.getByRole("button", { name: "homeNavigationConfirm" }),
    );

    expect(mockSetSelectedJob).toHaveBeenCalledWith(null);
    expect(window.localStorage.getItem("lastActiveJobId")).toBeNull();
    expect(window.scrollTo).toHaveBeenCalledWith({
      top: 0,
      behavior: "smooth",
    });
  });

  it("keeps the logo as a direct home link when no work is active", () => {
    render(<DashboardPage />);

    const homeLink = screen.getByRole("link", { name: "brandHomeLabel" });
    expect(homeLink).toHaveAttribute("href", "/");
    expect(
      screen.queryByRole("dialog", { name: "homeNavigationModalTitle" }),
    ).not.toBeInTheDocument();
  });

  it("protects a selected upload before processing has started", () => {
    // REGRESSION: work only counted after a server job existed, so a file
    // selected locally could be discarded by the logo without warning.
    window.scrollTo = jest.fn();
    render(<DashboardPage />);

    fireEvent.click(screen.getByRole("button", { name: "Select File" }));
    fireEvent.click(screen.getByRole("link", { name: "brandHomeLabel" }));

    expect(
      screen.getByRole("dialog", { name: "homeNavigationModalTitle" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "homeNavigationCancel" }),
    );
  });

  // REGRESSION: the disabled production UI exposed prices and a purchase
  // dialog even though paid-credit legal publication was not approved.
  it("keeps the balance visible without exposing a purchase entry point", () => {
    render(<DashboardPage />);

    fireEvent.click(screen.getByRole("button", { name: "creditsLabel: 125" }));

    expect(screen.getByTestId("credits-balance")).toHaveTextContent("125");
    expect(__refreshBalanceMock).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("dialog", {
        name: "creditPurchaseTitle",
      }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/€(?:1|3|10)\.00/)).not.toBeInTheDocument();
    expect(api.getCreditCatalog).not.toHaveBeenCalled();
  });

  it("opens the purchase dialog only after code-owned publication approval", async () => {
    mockPaidCreditLegalPublication.approved = true;
    render(<DashboardPage />);

    fireEvent.click(screen.getByRole("button", { name: "creditsLabel: 125" }));

    expect(
      await screen.findByRole("dialog", {
        name: "creditPurchaseTitle",
      }),
    ).toBeInTheDocument();
    expect(api.getCreditCatalog).toHaveBeenCalledTimes(1);
  });

  it("opens account settings only from the profile avatar", async () => {
    render(<DashboardPage />);

    expect(screen.queryByText("accountSettingsTitle")).not.toBeInTheDocument();
    const opener = screen.getByRole("button", { name: "profileLabel" });
    opener.focus();
    fireEvent.click(opener);
    expect(await screen.findByTestId("account-view")).toBeInTheDocument();
  });

  it("locks both document scrollers while the account dialog is open", async () => {
    const scrollTo = jest.fn();
    Object.defineProperty(window, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });
    Object.defineProperty(window, "scrollX", { configurable: true, value: 11 });
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      value: 355,
    });
    document.documentElement.style.overflow = "clip";
    document.body.style.overflow = "auto";

    render(<DashboardPage />);
    fireEvent.click(screen.getByRole("button", { name: "profileLabel" }));
    const dialog = await screen.findByRole("dialog", {
      name: "accountSettingsTitle",
    });

    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overscrollBehavior).toBe("none");
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.body.style.position).toBe("fixed");
    expect(document.body.style.top).toBe("-355px");
    expect(document.body.style.left).toBe("-11px");

    fireEvent.click(within(dialog).getByRole("button", { name: "closeLabel" }));

    expect(document.documentElement.style.overflow).toBe("clip");
    expect(document.body.style.overflow).toBe("auto");
    expect(document.body.style.position).toBe("");
    expect(scrollTo).toHaveBeenCalledWith(11, 355);

    document.documentElement.removeAttribute("style");
    document.body.removeAttribute("style");
  });

  it("closes the account dialog with Escape and restores focus to its opener", async () => {
    render(<DashboardPage />);

    const opener = screen.getByRole("button", { name: "profileLabel" });
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog", {
      name: "accountSettingsTitle",
    });
    const closeButton = within(dialog).getByRole("button", {
      name: "closeLabel",
    });

    await waitFor(() => expect(closeButton).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "accountSettingsTitle" }),
      ).not.toBeInTheDocument();
      expect(opener).toHaveFocus();
    });
  });

  // REGRESSION: logging out from the open account panel left the header inert,
  // so the guest "Sign in" link was visible but could not be clicked.
  it("restores an interactive sign-in link after logout from the account panel", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "profileLabel" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
    rerender(<DashboardPage />);

    const studioHeader = screen.getByLabelText("gsubs studio");
    expect(studioHeader).not.toHaveAttribute("inert");
    expect(studioHeader).not.toHaveAttribute("aria-hidden");
    expect(screen.getByRole("link", { name: "guestSignIn" })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("keeps the account session visible when server logout is not confirmed", async () => {
    const logout = jest.fn().mockRejectedValue(new Error("offline"));
    (useAuth as jest.Mock).mockReturnValue({
      user: mockUser,
      isLoading: false,
      refreshUser: mockRefreshUser,
      logout,
      login: mockLogin,
      register: mockRegister,
    });

    render(<DashboardPage />);
    fireEvent.click(screen.getByRole("button", { name: "profileLabel" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(logout).toHaveBeenCalledTimes(1);
      expect(screen.getByText("signOutError")).toBeInTheDocument();
    });
    expect(
      screen.getByRole("dialog", { name: "accountSettingsTitle" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("profileLabel")).toBeInTheDocument();
  });

  it("renders footer with privacy and terms links", () => {
    render(<DashboardPage />);

    const privacyLink = screen.getByText("legalPrivacyLink");
    const termsLink = screen.getByText("legalTermsLink");

    expect(privacyLink).toBeInTheDocument();
    expect(privacyLink.closest("a")).toHaveAttribute("href", "/privacy");

    expect(termsLink).toBeInTheDocument();
    expect(termsLink.closest("a")).toHaveAttribute("href", "/terms");
    expect(
      screen.getByRole("link", { name: /gsubs by Ascentia/i }),
    ).toHaveAttribute("href", "https://ascentia-gp.com/");
  });

  it("shows loading state when isLoading is true", () => {
    (useAuth as jest.Mock).mockReturnValue({
      user: null,
      isLoading: true,
      sessionUnavailable: false,
      refreshUser: mockRefreshUser,
      retrySession: mockRetrySession,
      logout: jest.fn(),
    });

    render(<DashboardPage />);
    const loadingState = screen.getByRole("status");
    expect(loadingState).toHaveAttribute("aria-live", "polite");
    expect(loadingState).toHaveAttribute("aria-busy", "true");
    expect(
      within(loadingState).getByRole("img", { name: "gsubs" }),
    ).toBeInTheDocument();
    expect(within(loadingState).getByText("loading")).toBeInTheDocument();
  });

  it("replaces an unbounded loading state with session recovery", () => {
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

    expect(
      screen.getByRole("heading", { name: "sessionUnavailableTitle" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "sessionRetry" }));
    expect(mockRetrySession).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("loading")).not.toBeInTheDocument();
  });

  it("renders the upload workspace for guests without redirecting", () => {
    (useAuth as jest.Mock).mockReturnValue({
      user: null,
      isLoading: false,
      refreshUser: mockRefreshUser,
      logout: jest.fn(),
      login: mockLogin,
      register: mockRegister,
    });

    render(<DashboardPage />);

    expect(screen.getByTestId("process-view")).toBeInTheDocument();
    const signInLink = screen.getByRole("link", { name: "guestSignIn" });
    expect(signInLink).toHaveAttribute("href", "/login");
    expect(screen.queryByLabelText("profileLabel")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("studio-header-credits"),
    ).not.toBeInTheDocument();
  });

  it("keeps the guest file selected through login and asks for cost before processing", async () => {
    (useAuth as jest.Mock).mockReturnValue({
      user: null,
      isLoading: false,
      refreshUser: mockRefreshUser,
      logout: jest.fn(),
      login: mockLogin,
      register: mockRegister,
    });
    (api.processVideo as jest.Mock).mockResolvedValue({
      id: "job123",
      status: "pending",
    });

    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));

    expect(
      await screen.findByRole("dialog", { name: "processingGateAuthTitle" }),
    ).toBeInTheDocument();
    expect(api.processVideo).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("loginEmailLabel"), {
      target: { value: "guest@example.com" },
    });
    fireEvent.change(screen.getByLabelText("loginPasswordLabel"), {
      target: { value: "correct horse battery staple" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "processingGateLoginSubmit" }),
    );

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith(
        "guest@example.com",
        "correct horse battery staple",
      );
      expect(api.getPointsBalance).toHaveBeenCalled();
    });

    expect(
      screen.getByRole("dialog", { name: "processingGateCostTitle" }),
    ).toBeInTheDocument();
    expect(api.processVideo).not.toHaveBeenCalled();

    await confirmProcessingCost();

    await waitFor(() =>
      expect(api.processVideo).toHaveBeenCalledWith(
        expect.any(File),
        expect.any(Object),
        expect.any(Object),
      ),
    );
  });
});
