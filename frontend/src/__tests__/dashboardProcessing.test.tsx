import React from "react";
import {
  __refreshBalanceMock,
  __setBalanceMock,
  __setPointsStateMock,
  act,
  api,
  capturedPollingCallbacks,
  capturedPollingJobId,
  confirmProcessingCost,
  DashboardPage,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
  installDashboardTestEnvironment,
} from "../../test-support/dashboardTestSupport";
import "@testing-library/jest-dom";

describe("DashboardPage processing", () => {
  installDashboardTestEnvironment();

  it("handles start processing success", async () => {
    (api.processVideo as jest.Mock).mockResolvedValue({
      id: "job123",
      status: "pending",
      balance: 800,
    });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();

    await waitFor(() => {
      expect(api.processVideo).toHaveBeenCalled();
    });
    expect(api.processVideo).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({
        authorized_credits: 30,
        watermark_enabled: true,
      }),
      expect.objectContaining({
        onProgress: expect.any(Function),
        onUploadComplete: expect.any(Function),
        signal: expect.any(AbortSignal),
      }),
    );
    expect(__setBalanceMock).toHaveBeenCalledWith(800);
  });

  it("reconfirms an authoritative 30-to-60 quote change before one explicit retry", async () => {
    // REGRESSION: a measured duration just above three minutes must never
    // auto-retry at a higher credit ceiling without the user's new consent.
    (api.processVideo as jest.Mock)
      .mockRejectedValueOnce(
        Object.assign(new Error("Processing quote changed"), {
          status: 409,
          code: "PROCESSING_QUOTE_CHANGED",
          details: {
            duration_seconds: 180.001,
            required_credits: 60,
          },
        }),
      )
      .mockResolvedValueOnce({ id: "job-quote-confirmed", status: "pending" });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();

    const updatedDialog = await screen.findByRole("dialog", {
      name: "processingGateCostTitle",
    });
    expect(within(updatedDialog).getByText("60")).toBeInTheDocument();
    expect(within(updatedDialog).getByRole("alert")).toHaveTextContent(
      "processingGateQuoteChanged",
    );
    expect(api.processVideo).toHaveBeenCalledTimes(1);
    const firstCall = (api.processVideo as jest.Mock).mock.calls[0];
    expect(firstCall[1]).toEqual(
      expect.objectContaining({
        authorized_credits: 30,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(api.processVideo).toHaveBeenCalledTimes(1);

    await confirmProcessingCost();
    await waitFor(() => expect(api.processVideo).toHaveBeenCalledTimes(2));

    const secondCall = (api.processVideo as jest.Mock).mock.calls[1];
    expect(secondCall[0]).toBe(firstCall[0]);
    expect(secondCall[1]).toEqual(
      expect.objectContaining({
        authorized_credits: 60,
      }),
    );
    const { authorized_credits: firstCredits, ...firstSettings } = firstCall[1];
    const { authorized_credits: secondCredits, ...secondSettings } =
      secondCall[1];
    expect(firstCredits).toBe(30);
    expect(secondCredits).toBe(60);
    expect(secondSettings).toEqual(firstSettings);
  });

  it("reconfirms an authoritative reprocess quote change before one explicit retry", async () => {
    // REGRESSION: reprocessing uses the same fail-closed consent boundary
    // as a new upload and must retain the source job and all settings.
    (api.reprocessJob as jest.Mock)
      .mockRejectedValueOnce(
        Object.assign(new Error("Processing quote changed"), {
          status: 409,
          code: "PROCESSING_QUOTE_CHANGED",
          details: {
            duration_seconds: 180.001,
            required_credits: 60,
          },
        }),
      )
      .mockResolvedValueOnce({
        id: "job-reprocess-quote-confirmed",
        status: "pending",
      });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Reprocess"));
    await confirmProcessingCost();

    const updatedDialog = await screen.findByRole("dialog", {
      name: "processingGateCostTitle",
    });
    expect(within(updatedDialog).getByText("60")).toBeInTheDocument();
    expect(within(updatedDialog).getByRole("alert")).toHaveTextContent(
      "processingGateQuoteChanged",
    );
    expect(api.reprocessJob).toHaveBeenCalledTimes(1);
    const firstCall = (api.reprocessJob as jest.Mock).mock.calls[0];
    expect(firstCall[0]).toBe("job1");
    expect(firstCall[1]).toEqual(
      expect.objectContaining({
        authorized_credits: 30,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(api.reprocessJob).toHaveBeenCalledTimes(1);

    await confirmProcessingCost();
    await waitFor(() => expect(api.reprocessJob).toHaveBeenCalledTimes(2));

    const secondCall = (api.reprocessJob as jest.Mock).mock.calls[1];
    expect(secondCall[0]).toBe(firstCall[0]);
    expect(secondCall[1]).toEqual(
      expect.objectContaining({
        authorized_credits: 60,
      }),
    );
    const { authorized_credits: firstCredits, ...firstSettings } = firstCall[1];
    const { authorized_credits: secondCredits, ...secondSettings } =
      secondCall[1];
    expect(firstCredits).toBe(30);
    expect(secondCredits).toBe(60);
    expect(secondSettings).toEqual(firstSettings);
  });

  it("uses promotional credits for mock processing", async () => {
    // REGRESSION: mock processing used aiSpendableBalance and blocked a
    // user with 100 promotional credits and zero purchased credits.
    __setPointsStateMock({
      balance: 100,
      paidBalance: 0,
      promotionalBalance: 100,
      reversalDebt: 0,
      aiSpendableBalance: 0,
    });
    (api.processVideo as jest.Mock).mockResolvedValue({
      id: "job-mock",
      status: "pending",
      balance: 70,
    });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));

    expect(
      screen.getByText("processingGateTotalBalanceLabel"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("processingGateBalanceLabel"),
    ).not.toBeInTheDocument();
    await confirmProcessingCost();

    await waitFor(() => {
      expect(api.processVideo).toHaveBeenCalledWith(
        expect.any(File),
        expect.objectContaining({ transcribe_provider: "mock" }),
        expect.any(Object),
      );
    });
  });

  it("still requires purchased credits for an external provider", () => {
    __setPointsStateMock({
      balance: 100,
      paidBalance: 0,
      promotionalBalance: 100,
      reversalDebt: 0,
      aiSpendableBalance: 0,
    });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Reprocess"));

    expect(screen.getByText("processingGateBalanceLabel")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "processingGateConfirm",
      }),
    ).not.toBeInTheDocument();
    expect(api.reprocessJob).not.toHaveBeenCalled();
  });

  it("keeps production mock uploads on the local processing endpoint", async () => {
    (api.processVideo as jest.Mock).mockResolvedValue({
      id: "job123",
      status: "pending",
    });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();

    await waitFor(() => {
      expect(api.processVideo).toHaveBeenCalledWith(
        expect.any(File),
        expect.objectContaining({ transcribe_provider: "mock" }),
        expect.any(Object),
      );
    });
  });

  it("shows direct-upload progress and only exposes cancellation while it is safe", async () => {
    type UploadCallbacks = {
      onProgress?: (percent: number) => void;
      onUploadComplete?: () => void;
      signal?: AbortSignal;
    };
    let uploadCallbacks: UploadCallbacks | undefined;
    let resolveProcess:
      ((job: { id: string; status: string }) => void) | undefined;
    (api.processVideo as jest.Mock).mockImplementation(
      (_file: File, _settings: unknown, callbacks: UploadCallbacks) => {
        uploadCallbacks = callbacks;
        return new Promise((resolve) => {
          resolveProcess = resolve;
        });
      },
    );
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();
    await waitFor(() => expect(uploadCallbacks).toBeDefined());

    expect(screen.getByText("Cancel Active Process")).toBeInTheDocument();
    act(() => uploadCallbacks?.onProgress?.(37));
    expect(screen.getByTestId("process-progress")).toHaveTextContent("37");
    expect(screen.getByTestId("process-status")).toHaveTextContent(
      "statusUploading 37%",
    );

    act(() => uploadCallbacks?.onUploadComplete?.());
    expect(screen.queryByText("Cancel Active Process")).not.toBeInTheDocument();
    expect(screen.getByTestId("process-status")).toHaveTextContent(
      "statusProcessing",
    );

    await act(async () => {
      resolveProcess?.({ id: "job-progress", status: "pending" });
      await Promise.resolve();
    });
    expect(screen.getByText("Cancel Active Process")).toBeInTheDocument();
  });

  it("aborts a slow direct upload and keeps the selected file available", async () => {
    type UploadCallbacks = { signal?: AbortSignal };
    let uploadSignal: AbortSignal | undefined;
    (api.processVideo as jest.Mock).mockImplementation(
      (_file: File, _settings: unknown, callbacks: UploadCallbacks) => {
        uploadSignal = callbacks.signal;
        return new Promise((_resolve, reject) => {
          callbacks.signal?.addEventListener(
            "abort",
            () => {
              reject(
                Object.assign(new Error("Upload cancelled"), {
                  code: "upload_cancelled",
                }),
              );
            },
            { once: true },
          );
        });
      },
    );
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();
    const cancelButton = await screen.findByText("Cancel Active Process");
    fireEvent.click(cancelButton);

    await waitFor(() => expect(uploadSignal?.aborted).toBe(true));
    expect(screen.getByTestId("process-error")).toHaveTextContent(
      "processingCancelled",
    );
    expect(screen.queryByText("Cancel Active Process")).not.toBeInTheDocument();
    expect(api.cancelJob).not.toHaveBeenCalled();
  });

  it("keeps polling a server job until cancellation cleanup is terminal", async () => {
    // REGRESSION: a successful cancel request previously cleared jobId and
    // stopped polling before the server had securely removed local files.
    (api.processVideo as jest.Mock).mockResolvedValue({
      id: "job-cancel-server",
      status: "pending",
    });
    (api.cancelJob as jest.Mock).mockResolvedValue({
      id: "job-cancel-server",
      status: "cancelling",
    });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();

    const cancelButton = await screen.findByText("Cancel Active Process");
    expect(capturedPollingJobId).toBe("job-cancel-server");
    expect(window.localStorage.getItem("lastActiveJobId")).toBe(
      "job-cancel-server",
    );
    fireEvent.click(cancelButton);

    await waitFor(() => {
      expect(api.cancelJob).toHaveBeenCalledWith("job-cancel-server");
      expect(screen.getByTestId("process-status")).toHaveTextContent(
        "cancellationRequested",
      );
    });
    expect(screen.getByTestId("process-processing")).toHaveTextContent("true");
    expect(screen.queryByText("Cancel Active Process")).not.toBeInTheDocument();
    expect(capturedPollingJobId).toBe("job-cancel-server");

    act(() => {
      capturedPollingCallbacks!.onProgress(50, "cancellationRequested");
    });
    expect(capturedPollingJobId).toBe("job-cancel-server");
    expect(screen.getByTestId("process-processing")).toHaveTextContent("true");

    act(() => {
      // useJobPolling maps the terminal `cancelled` state to onFailed.
      capturedPollingCallbacks!.onFailed("processingCancelled");
    });
    await waitFor(() => {
      expect(capturedPollingJobId).toBeNull();
      expect(screen.getByTestId("process-processing")).toHaveTextContent(
        "false",
      );
      expect(screen.getByTestId("process-error")).toHaveTextContent(
        "processingCancelled",
      );
      expect(window.localStorage.getItem("lastActiveJobId")).toBeNull();
    });
  });

  it("uses the single local raw-stream client path for a production external provider", async () => {
    // REGRESSION: production external-provider uploads must stay on the
    // one local raw-stream client path with no cloud or multipart branch.
    (api.processVideo as jest.Mock).mockResolvedValue({
      id: "job-local-production",
      status: "pending",
    });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start External Process"));
    await confirmProcessingCost();

    await waitFor(() => {
      expect(api.processVideo).toHaveBeenCalledWith(
        expect.any(File),
        expect.objectContaining({ transcribe_provider: "groq" }),
        expect.objectContaining({
          onProgress: expect.any(Function),
          onUploadComplete: expect.any(Function),
          signal: expect.any(AbortSignal),
        }),
      );
    });
  });

  it("refreshes balance when process response has no balance", async () => {
    (api.processVideo as jest.Mock).mockResolvedValue({
      id: "job123",
      status: "pending",
    });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();

    await waitFor(() => {
      expect(api.processVideo).toHaveBeenCalled();
    });
    expect(__refreshBalanceMock).toHaveBeenCalled();
  });

  it("handles start processing error", async () => {
    (api.processVideo as jest.Mock).mockRejectedValue(
      Object.assign(new Error("Upload failed"), {
        code: "upload_network_error",
      }),
    );
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();

    await waitFor(() => {
      expect(api.processVideo).toHaveBeenCalled();
    });
    expect(screen.getByTestId("process-error")).toHaveTextContent(
      "uploadConnectionError",
    );
  });

  it("refreshes refunded credits after the server terminates a stalled upload", async () => {
    (api.processVideo as jest.Mock).mockRejectedValue(
      Object.assign(new Error("Upload stalled before completion"), {
        status: 408,
      }),
    );
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Select File"));
    fireEvent.click(screen.getByText("Start Process"));
    await confirmProcessingCost();

    await waitFor(() => {
      expect(api.processVideo).toHaveBeenCalled();
    });
    expect(screen.getByTestId("process-error")).toHaveTextContent(
      "uploadConnectionError",
    );
    expect(__refreshBalanceMock).toHaveBeenCalledTimes(1);
  });

  it("updates balance on reprocess success", async () => {
    (api.reprocessJob as jest.Mock).mockResolvedValue({
      id: "job234",
      status: "pending",
      balance: 700,
    });
    render(<DashboardPage />);

    fireEvent.click(screen.getByText("Reprocess"));
    await confirmProcessingCost();

    await waitFor(() => {
      expect(api.reprocessJob).toHaveBeenCalledWith("job1", expect.any(Object));
    });
    expect(api.reprocessJob).toHaveBeenCalledWith(
      "job1",
      expect.objectContaining({
        authorized_credits: 30,
        watermark_enabled: true,
      }),
    );
    expect(__setBalanceMock).toHaveBeenCalledWith(700);
  });
});
