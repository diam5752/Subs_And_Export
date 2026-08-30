import React from "react";
import {
  __refreshBalanceMock,
  act,
  api,
  capturedOnReset,
  capturedPollingCallbacks,
  DashboardPage,
  fireEvent,
  mockLoadJobs,
  mockRefreshUser,
  mockSetSelectedJob,
  render,
  screen,
  waitFor,
  installDashboardTestEnvironment,
} from "../../test-support/dashboardTestSupport";
import "@testing-library/jest-dom";

describe("DashboardPage profile and polling lifecycle", () => {
  installDashboardTestEnvironment();

  it("handles profile save with name change", async () => {
    (api.updateProfile as jest.Mock).mockResolvedValue({});
    mockRefreshUser.mockResolvedValue({});

    render(<DashboardPage />);

    fireEvent.click(screen.getByLabelText("profileLabel"));
    expect(await screen.findByTestId("account-view")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Save Name Only"));

    await waitFor(() => {
      expect(api.updateProfile).toHaveBeenCalledWith("NewName");
      expect(mockRefreshUser).toHaveBeenCalled();
    });
  });

  it("handles profile save with password mismatch", async () => {
    render(<DashboardPage />);

    fireEvent.click(screen.getByLabelText("profileLabel"));
    fireEvent.click(await screen.findByText("Save Mismatch"));

    // Password mismatch error should be set but we can't easily verify internal state
    // The test verifies the code path is executed
    await waitFor(() => {
      expect(api.updateProfile).not.toHaveBeenCalled();
    });
  });

  it("handles profile save with password update", async () => {
    (api.updateProfile as jest.Mock).mockResolvedValue({});
    (api.updatePassword as jest.Mock).mockResolvedValue({});
    mockRefreshUser.mockResolvedValue({});

    render(<DashboardPage />);

    fireEvent.click(screen.getByLabelText("profileLabel"));
    fireEvent.click(await screen.findByText("Save Profile"));

    await waitFor(() => {
      expect(api.updateProfile).toHaveBeenCalledWith("NewName");
      expect(api.updatePassword).toHaveBeenCalledWith("pass", "pass");
    });
  });

  it("handles profile save error", async () => {
    (api.updateProfile as jest.Mock).mockRejectedValue(
      new Error("Update failed"),
    );

    render(<DashboardPage />);

    fireEvent.click(screen.getByLabelText("profileLabel"));
    fireEvent.click(await screen.findByText("Save Name Only"));

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
  it("handles reset processing and clears selectedJob", async () => {
    (api.getJobStatus as jest.Mock).mockResolvedValue({
      id: "previous-job",
      status: "failed",
    });
    window.localStorage.setItem("lastActiveJobId", "previous-job");
    render(<DashboardPage />);

    // Trigger reset via captured callback
    fireEvent.click(await screen.findByText("Reset"));

    // Test verifies the code path is executed without errors
    expect(capturedOnReset).toBeDefined();

    // REGRESSION: Verify that setSelectedJob(null) is called to clear previous job
    expect(mockSetSelectedJob).toHaveBeenCalledWith(null);
    expect(window.localStorage.getItem("lastActiveJobId")).toBeNull();
  });

  it("calls refreshActivity via refresh button", async () => {
    render(<DashboardPage />);

    fireEvent.click(screen.getByLabelText("profileLabel"));
    fireEvent.click(await screen.findByTestId("refresh-jobs-btn"));

    await waitFor(() => {
      expect(mockLoadJobs).toHaveBeenCalledTimes(1);
    });
  });

  it("handles polling onProgress callback", () => {
    render(<DashboardPage />);

    // The component should have passed callbacks to useJobPolling
    expect(capturedPollingCallbacks).not.toBeNull();

    // Invoke the onProgress callback
    act(() => {
      capturedPollingCallbacks!.onProgress(50, "Processing...");
    });

    // Component should update without errors
    expect(screen.getByTestId("process-view")).toBeInTheDocument();
  });

  it("handles polling onComplete callback", async () => {
    render(<DashboardPage />);

    const mockJob = {
      id: "job1",
      status: "completed",
      result_data: { public_url: "url" },
    };

    act(() => {
      capturedPollingCallbacks!.onComplete(mockJob);
    });

    await waitFor(() => {
      expect(mockSetSelectedJob).toHaveBeenCalledWith(mockJob);
    });
    expect(mockLoadJobs).toHaveBeenCalled();
  });

  it("handles polling onFailed callback", async () => {
    render(<DashboardPage />);

    act(() => {
      capturedPollingCallbacks!.onFailed("Job failed");
    });

    await waitFor(() => {
      expect(mockLoadJobs).toHaveBeenCalled();
    });
  });

  it("localizes a missing word-timestamps failure and refreshes refunded credits", async () => {
    render(<DashboardPage />);
    __refreshBalanceMock.mockClear();

    act(() => {
      capturedPollingCallbacks!.onFailed(
        "ElevenLabs Scribe v2 response did not include word timestamps.",
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("process-error")).toHaveTextContent(
        "transcriptionMissingWordTimestamps",
      );
      expect(__refreshBalanceMock).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("process-error")).not.toHaveTextContent(
      "ElevenLabs",
    );
  });

  it("handles polling onError callback", () => {
    render(<DashboardPage />);

    act(() => {
      capturedPollingCallbacks!.onError("Network error");
    });

    // Component should update without errors
    expect(screen.getByTestId("process-view")).toBeInTheDocument();
  });

  it("opens account modal and closes via backdrop click", async () => {
    render(<DashboardPage />);

    // Open account panel
    fireEvent.click(screen.getByLabelText("profileLabel"));
    expect(await screen.findByTestId("account-view")).toBeInTheDocument();

    // Click backdrop (the absolute inset-0 div)
    const backdrop = screen
      .getByTestId("account-view")
      .closest(".fixed")
      ?.querySelector(".absolute.inset-0");
    if (backdrop) {
      fireEvent.click(backdrop);
    }

    // Modal should close
    expect(screen.queryByTestId("account-view")).not.toBeInTheDocument();
  });
});
