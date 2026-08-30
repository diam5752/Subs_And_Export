import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import { PointsProvider, usePoints } from "@/context/PointsContext";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

jest.mock("@/lib/api", () => ({
  api: {
    getPointsBalance: jest.fn(),
  },
}));

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

function PointsHarness() {
  const {
    balance,
    paidBalance,
    promotionalBalance,
    reversalDebt,
    aiSpendableBalance,
    isLoading,
    error,
    refreshBalance,
    setBalance,
    setWallet,
  } = usePoints();

  return (
    <div>
      <div data-testid="balance">
        {balance === null ? "null" : String(balance)}
      </div>
      <div data-testid="paid-balance">
        {paidBalance === null ? "null" : String(paidBalance)}
      </div>
      <div data-testid="promo-balance">
        {promotionalBalance === null ? "null" : String(promotionalBalance)}
      </div>
      <div data-testid="reversal-debt">
        {reversalDebt === null ? "null" : String(reversalDebt)}
      </div>
      <div data-testid="ai-spendable">
        {aiSpendableBalance === null ? "null" : String(aiSpendableBalance)}
      </div>
      <div data-testid="loading">{String(isLoading)}</div>
      <div data-testid="error">{error ?? "none"}</div>
      <button type="button" onClick={() => void refreshBalance()}>
        refresh-balance
      </button>
      <button type="button" onClick={() => setBalance(123)}>
        set-balance
      </button>
      <button
        type="button"
        onClick={() =>
          setWallet({
            balance: 210,
            paid_balance: 150,
            promotional_balance: 60,
            reversal_debt: 10,
            ai_spendable_balance: 140,
          })
        }
      >
        set-wallet
      </button>
    </div>
  );
}

function StatefulChild() {
  const [value, setValue] = React.useState("");

  return (
    <input
      aria-label="local-work"
      value={value}
      onChange={(event) => setValue(event.target.value)}
    />
  );
}

interface CapturedWalletActions {
  setWallet: ReturnType<typeof usePoints>["setWallet"];
  refreshBalance: ReturnType<typeof usePoints>["refreshBalance"];
}

function WalletActionsCapture({
  onCapture,
}: {
  onCapture: (actions: CapturedWalletActions) => void;
}) {
  const { balance, isLoading, refreshBalance, setWallet } = usePoints();

  React.useEffect(() => {
    onCapture({ refreshBalance, setWallet });
  }, [onCapture, refreshBalance, setWallet]);

  return (
    <div>
      <div data-testid="captured-balance">
        {balance === null ? "null" : String(balance)}
      </div>
      <div data-testid="captured-loading">{String(isLoading)}</div>
    </div>
  );
}

describe("PointsContext", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useAuth as jest.Mock).mockReturnValue({
      user: { id: "u1", email: "user@example.com" },
      isLoading: false,
    });
    (api.getPointsBalance as jest.Mock).mockResolvedValue({ balance: 42 });
  });

  it("loads the balance for authenticated users", async () => {
    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    await waitFor(() => {
      expect(api.getPointsBalance).toHaveBeenCalled();
      expect(screen.getByTestId("balance")).toHaveTextContent("42");
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });
  });

  it("resets state without calling the API when no user is present", async () => {
    (useAuth as jest.Mock).mockReturnValue({
      user: null,
      isLoading: false,
    });

    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    await waitFor(() => {
      expect(api.getPointsBalance).not.toHaveBeenCalled();
      expect(screen.getByTestId("balance")).toHaveTextContent("null");
      expect(screen.getByTestId("error")).toHaveTextContent("none");
    });
  });

  it("waits for auth loading before fetching", async () => {
    (useAuth as jest.Mock).mockReturnValue({
      user: { id: "u1" },
      isLoading: true,
    });

    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    await waitFor(() => {
      expect(api.getPointsBalance).not.toHaveBeenCalled();
      expect(screen.getByTestId("balance")).toHaveTextContent("null");
    });
  });

  it("surfaces API errors and allows manual retry", async () => {
    (api.getPointsBalance as jest.Mock)
      .mockRejectedValueOnce(new Error("balance failed"))
      .mockResolvedValueOnce({ balance: 77 });

    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("error")).toHaveTextContent("balance failed");
    });

    fireEvent.click(screen.getByRole("button", { name: "refresh-balance" }));

    await waitFor(() => {
      expect(screen.getByTestId("balance")).toHaveTextContent("77");
      expect(screen.getByTestId("error")).toHaveTextContent("none");
    });
  });

  it("exposes setBalance for local optimistic updates", async () => {
    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("balance")).toHaveTextContent("42"),
    );

    fireEvent.click(screen.getByRole("button", { name: "set-balance" }));

    expect(screen.getByTestId("balance")).toHaveTextContent("123");
  });

  it("updates every wallet bucket through setWallet", async () => {
    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("balance")).toHaveTextContent("42"),
    );
    fireEvent.click(screen.getByRole("button", { name: "set-wallet" }));

    expect(screen.getByTestId("balance")).toHaveTextContent("210");
    expect(screen.getByTestId("paid-balance")).toHaveTextContent("150");
    expect(screen.getByTestId("promo-balance")).toHaveTextContent("60");
    expect(screen.getByTestId("reversal-debt")).toHaveTextContent("10");
    expect(screen.getByTestId("ai-spendable")).toHaveTextContent("140");
  });

  it("does not let a stale balance request overwrite an authoritative wallet update", async () => {
    let resolveInitialBalance!: (value: {
      balance: number;
      paid_balance: number;
      promotional_balance: number;
      reversal_debt: number;
      ai_spendable_balance: number;
    }) => void;
    (api.getPointsBalance as jest.Mock).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveInitialBalance = resolve;
      }),
    );

    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );
    await waitFor(() => expect(api.getPointsBalance).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "set-wallet" }));
    expect(screen.getByTestId("balance")).toHaveTextContent("210");
    expect(screen.getByTestId("loading")).toHaveTextContent("false");

    await act(async () =>
      resolveInitialBalance({
        balance: 800,
        paid_balance: 700,
        promotional_balance: 100,
        reversal_debt: 0,
        ai_spendable_balance: 700,
      }),
    );

    expect(screen.getByTestId("balance")).toHaveTextContent("210");
    expect(screen.getByTestId("paid-balance")).toHaveTextContent("150");
    expect(screen.getByTestId("promo-balance")).toHaveTextContent("60");
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
  });

  it("keeps the newest same-session refresh when responses arrive out of order", async () => {
    let resolveOlderRefresh!: (value: { balance: number }) => void;
    let resolveNewerRefresh!: (value: { balance: number }) => void;
    (api.getPointsBalance as jest.Mock)
      .mockResolvedValueOnce({ balance: 10 })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveOlderRefresh = resolve;
        }),
      )
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveNewerRefresh = resolve;
        }),
      );

    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("balance")).toHaveTextContent("10"),
    );

    fireEvent.click(screen.getByRole("button", { name: "refresh-balance" }));
    fireEvent.click(screen.getByRole("button", { name: "refresh-balance" }));

    await act(async () => resolveNewerRefresh({ balance: 30 }));
    expect(screen.getByTestId("balance")).toHaveTextContent("30");
    expect(screen.getByTestId("loading")).toHaveTextContent("false");

    await act(async () => resolveOlderRefresh({ balance: 20 }));
    expect(screen.getByTestId("balance")).toHaveTextContent("30");
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
  });

  it("uses a safe fallback message for non-Error refresh failures", async () => {
    (api.getPointsBalance as jest.Mock)
      .mockResolvedValueOnce({ balance: 42 })
      .mockRejectedValueOnce("offline");

    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("balance")).toHaveTextContent("42"),
    );
    fireEvent.click(screen.getByRole("button", { name: "refresh-balance" }));

    await waitFor(() => {
      expect(screen.getByTestId("error")).toHaveTextContent(
        "Failed to load balance",
      );
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });
  });

  it("preserves child state when an anonymous session signs in", async () => {
    (useAuth as jest.Mock).mockReturnValue({
      user: null,
      isLoading: false,
    });

    const view = render(
      <PointsProvider>
        <StatefulChild />
      </PointsProvider>,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "local-work" }), {
      target: { value: "guest-video-selected" },
    });

    (useAuth as jest.Mock).mockReturnValue({
      user: { id: "u1", email: "user@example.com" },
      isLoading: false,
    });
    view.rerender(
      <PointsProvider>
        <StatefulChild />
      </PointsProvider>,
    );

    expect(screen.getByRole("textbox", { name: "local-work" })).toHaveValue(
      "guest-video-selected",
    );
    await waitFor(() => expect(api.getPointsBalance).toHaveBeenCalledTimes(1));
  });

  it("throws when usePoints is called outside a provider", () => {
    expect(() => render(<PointsHarness />)).toThrow(
      "usePoints must be used within a PointsProvider",
    );
  });

  it("derives omitted wallet buckets and blocks AI spend while debt exists", async () => {
    (api.getPointsBalance as jest.Mock).mockResolvedValue({
      balance: 50,
      paid_balance: 30,
      reversal_debt: 2,
    });

    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("balance")).toHaveTextContent("50"),
    );
    expect(screen.getByTestId("paid-balance")).toHaveTextContent("30");
    expect(screen.getByTestId("promo-balance")).toHaveTextContent("20");
    expect(screen.getByTestId("reversal-debt")).toHaveTextContent("2");
    expect(screen.getByTestId("ai-spendable")).toHaveTextContent("0");
  });

  it("does not fetch when a guest manually asks for a balance refresh", async () => {
    (useAuth as jest.Mock).mockReturnValue({ user: null, isLoading: false });
    render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "refresh-balance" }));
    await act(async () => undefined);
    expect(api.getPointsBalance).not.toHaveBeenCalled();
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
  });

  it("ignores a manual refresh that resolves for a previous account session", async () => {
    let resolveOldRefresh!: (value: { balance: number }) => void;
    (api.getPointsBalance as jest.Mock)
      .mockResolvedValueOnce({ balance: 10 })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveOldRefresh = resolve;
        }),
      )
      .mockResolvedValueOnce({ balance: 22 });
    const view = render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("balance")).toHaveTextContent("10"),
    );

    fireEvent.click(screen.getByRole("button", { name: "refresh-balance" }));
    (useAuth as jest.Mock).mockReturnValue({
      user: { id: "u2", email: "second@example.com" },
      isLoading: false,
    });
    view.rerender(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("balance")).toHaveTextContent("22"),
    );

    await act(async () => resolveOldRefresh({ balance: 99 }));
    expect(screen.getByTestId("balance")).toHaveTextContent("22");
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
  });

  it("does not let a setter from an old account invalidate the new account fetch", async () => {
    let resolveNewAccount!: (value: { balance: number }) => void;
    const capturedActions: CapturedWalletActions[] = [];
    const captureActions = (actions: CapturedWalletActions) => {
      capturedActions.push(actions);
    };
    (api.getPointsBalance as jest.Mock)
      .mockResolvedValueOnce({ balance: 10 })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveNewAccount = resolve;
        }),
      );
    const view = render(
      <PointsProvider>
        <WalletActionsCapture onCapture={captureActions} />
      </PointsProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("captured-balance")).toHaveTextContent("10"),
    );
    const oldAccountActions = capturedActions.at(-1);
    if (!oldAccountActions)
      throw new Error("Expected the first account actions to be captured.");

    (useAuth as jest.Mock).mockReturnValue({
      user: { id: "u2", email: "second@example.com" },
      isLoading: false,
    });
    view.rerender(
      <PointsProvider>
        <WalletActionsCapture onCapture={captureActions} />
      </PointsProvider>,
    );
    await waitFor(() => expect(api.getPointsBalance).toHaveBeenCalledTimes(2));

    act(() => {
      oldAccountActions.setWallet({
        balance: 999,
        paid_balance: 999,
        promotional_balance: 0,
        reversal_debt: 0,
        ai_spendable_balance: 999,
      });
      void oldAccountActions.refreshBalance();
    });
    expect(api.getPointsBalance).toHaveBeenCalledTimes(2);
    await act(async () => resolveNewAccount({ balance: 22 }));

    expect(screen.getByTestId("captured-balance")).toHaveTextContent("22");
    expect(screen.getByTestId("captured-loading")).toHaveTextContent("false");
  });

  it("does not publish an automatic request that resolves after unmount", async () => {
    let resolveBalance!: (value: { balance: number }) => void;
    (api.getPointsBalance as jest.Mock).mockReturnValue(
      new Promise((resolve) => {
        resolveBalance = resolve;
      }),
    );
    const view = render(
      <PointsProvider>
        <PointsHarness />
      </PointsProvider>,
    );

    view.unmount();
    await act(async () => resolveBalance({ balance: 88 }));
    expect(api.getPointsBalance).toHaveBeenCalledTimes(1);
  });
});
