import React from "react";
import {
  __setWalletMock,
  act,
  api,
  DashboardPage,
  fireEvent,
  render,
  screen,
  waitFor,
  installDashboardTestEnvironment,
  mockUser,
  useAuth,
} from "../../test-support/dashboardTestSupport";
import "@testing-library/jest-dom";

describe("DashboardPage checkout return", () => {
  installDashboardTestEnvironment();

  it("shows an immediate fixed pending notice while the first checkout read is unresolved", async () => {
    const sessionId = "cs_test_slow_first_read";
    let resolveStatus!: (value: unknown) => void;
    window.history.replaceState(
      {},
      "",
      `/?checkout=success&session_id=${sessionId}`,
    );
    (api.getCreditCheckoutStatus as jest.Mock).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveStatus = resolve;
      }),
    );

    render(<DashboardPage />);

    const notice = await screen.findByTestId("checkout-return-notice");
    expect(notice).toHaveTextContent("creditPurchasePending");
    expect(notice).toHaveAttribute("data-kind", "pending");
    expect(notice.closest("main")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "profileLabel" }));
    expect(
      await screen.findByRole("dialog", { name: "accountSettingsTitle" }),
    ).toBeInTheDocument();
    expect(notice).toHaveAttribute("aria-hidden", "true");
    expect(notice).toHaveAttribute("inert");
    fireEvent.click(screen.getByRole("button", { name: "closeLabel" }));
    expect(notice).not.toHaveAttribute("aria-hidden");
    expect(notice).not.toHaveAttribute("inert");

    await act(async () =>
      resolveStatus({
        purchase_id: "purchase-slow-first-read",
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status: "paid",
        checkout_session_id: sessionId,
        wallet: {
          balance: 225,
          paid_balance: 100,
          promotional_balance: 125,
          reversal_debt: 0,
          ai_spendable_balance: 100,
        },
      }),
    );

    expect(notice).toHaveTextContent("creditPurchaseSuccess");
    expect(notice).toHaveAttribute("data-kind", "success");
  });

  it.each(["paid", "partially_refunded"])(
    "reconciles an already-%s checkout, refreshes the wallet, and clears the return URL",
    async (status) => {
      const sessionId = `cs_test_${status}`;
      const wallet = {
        balance: 225,
        paid_balance: 100,
        promotional_balance: 125,
        reversal_debt: 0,
        ai_spendable_balance: 100,
      };
      window.history.replaceState(
        {},
        "",
        `/?checkout=success&session_id=${sessionId}`,
      );
      (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
        purchase_id: `purchase-${status}`,
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status,
        checkout_session_id: sessionId,
        wallet,
      });

      render(<DashboardPage />);

      await waitFor(() => {
        expect(screen.getByRole("status")).toHaveTextContent(
          "creditPurchaseSuccess",
        );
      });
      expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
      expect(__setWalletMock).toHaveBeenCalledWith(wallet);
      expect(
        screen.getByRole("link", { name: "billingContractDownload" }),
      ).toBeInTheDocument();
      await waitFor(() => {
        expect(window.location.search).toBe("");
      });
    },
  );

  it("hides a paid checkout notice as soon as the authenticated account changes", async () => {
    const sessionId = "cs_test_account_isolation";
    const wallet = {
      balance: 225,
      paid_balance: 100,
      promotional_balance: 125,
      reversal_debt: 0,
      ai_spendable_balance: 100,
    };
    window.history.replaceState(
      {},
      "",
      `/?checkout=success&session_id=${sessionId}`,
    );
    (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
      purchase_id: "purchase-account-isolation",
      package_key: "starter",
      credits: 100,
      amount_eur_cents: 100,
      status: "paid",
      checkout_session_id: sessionId,
      wallet,
    });

    const { rerender } = render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "creditPurchaseSuccess",
      );
    });
    expect(
      screen.getByRole("link", { name: "billingContractDownload" }),
    ).toBeInTheDocument();

    (useAuth as jest.Mock).mockReturnValue({
      user: null,
      isLoading: false,
      sessionUnavailable: false,
      betaCreditsAwarded: 0,
      refreshUser: jest.fn(),
      retrySession: jest.fn(),
      logout: jest.fn(),
      login: jest.fn(),
      register: jest.fn(),
      dismissBetaCreditsAwarded: jest.fn(),
    });
    rerender(<DashboardPage />);

    expect(
      screen.queryByTestId("checkout-return-notice"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("creditPurchaseSuccess")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "billingContractDownload" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "creditPurchaseRetry" }),
    ).not.toBeInTheDocument();

    (useAuth as jest.Mock).mockReturnValue({
      user: { ...mockUser, id: "user-b", email: "user-b@example.com" },
      isLoading: false,
      sessionUnavailable: false,
      betaCreditsAwarded: 0,
      refreshUser: jest.fn(),
      retrySession: jest.fn(),
      logout: jest.fn(),
      login: jest.fn(),
      register: jest.fn(),
      dismissBetaCreditsAwarded: jest.fn(),
    });
    rerender(<DashboardPage />);

    expect(
      screen.queryByTestId("checkout-return-notice"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("creditPurchaseSuccess")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "billingContractDownload" }),
    ).not.toBeInTheDocument();
  });

  it("cleans a cancelled checkout once while preserving unrelated URL state", async () => {
    window.history.replaceState(
      {},
      "",
      "/?checkout=cancelled&session_id=cs_test_cancelled&campaign=beta#credits",
    );

    render(<DashboardPage />);

    expect(await screen.findByRole("status")).toHaveTextContent(
      "creditPurchaseCancelled",
    );
    expect(api.getCreditCheckoutStatus).not.toHaveBeenCalled();
    expect(window.location.search).toBe("?campaign=beta");
    expect(window.location.hash).toBe("#credits");
  });

  it("keeps every known nonterminal checkout status until it becomes paid", async () => {
    jest.useFakeTimers();
    const sessionId = "cs_test_pending_then_paid";
    const pendingWallet = {
      balance: 125,
      paid_balance: 0,
      promotional_balance: 125,
      reversal_debt: 0,
      ai_spendable_balance: 0,
    };
    const paidWallet = {
      balance: 225,
      paid_balance: 100,
      promotional_balance: 125,
      reversal_debt: 0,
      ai_spendable_balance: 100,
    };
    window.history.replaceState(
      {},
      "",
      `/?checkout=success&session_id=${sessionId}`,
    );
    (api.getCreditCheckoutStatus as jest.Mock)
      .mockResolvedValueOnce({
        purchase_id: "purchase-pending",
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status: "creating",
        checkout_session_id: sessionId,
        wallet: pendingWallet,
      })
      .mockResolvedValueOnce({
        purchase_id: "purchase-pending",
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status: "checkout_created",
        checkout_session_id: sessionId,
        wallet: pendingWallet,
      })
      .mockResolvedValueOnce({
        purchase_id: "purchase-pending",
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status: "awaiting_payment",
        checkout_session_id: sessionId,
        wallet: pendingWallet,
      })
      .mockResolvedValueOnce({
        purchase_id: "purchase-pending",
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status: "paid",
        checkout_session_id: sessionId,
        wallet: paidWallet,
      });

    render(<DashboardPage />);

    await act(async () => {
      await Promise.resolve();
    });
    expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status")).toHaveTextContent(
      "creditPurchasePending",
    );
    expect(window.location.search).toContain(
      "session_id=cs_test_pending_then_paid",
    );

    await act(async () => {
      jest.advanceTimersByTime(1_000);
      await Promise.resolve();
    });
    expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toHaveTextContent(
      "creditPurchasePending",
    );
    expect(window.location.search).toContain(
      "session_id=cs_test_pending_then_paid",
    );

    await act(async () => {
      jest.advanceTimersByTime(2_000);
      await Promise.resolve();
    });
    expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("status")).toHaveTextContent(
      "creditPurchasePending",
    );
    expect(window.location.search).toContain(
      "session_id=cs_test_pending_then_paid",
    );

    await act(async () => {
      jest.advanceTimersByTime(4_000);
      await Promise.resolve();
    });

    expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(4);
    expect(screen.getByRole("status")).toHaveTextContent(
      "creditPurchaseSuccess",
    );
    expect(__setWalletMock).toHaveBeenLastCalledWith(paidWallet);
    expect(window.location.search).toBe("");
  });

  it("preserves a slow checkout session and provides a bounded manual retry", async () => {
    jest.useFakeTimers();
    const sessionId = "cs_test_slow_pending";
    const pendingStatus = {
      purchase_id: "purchase-slow",
      package_key: "starter",
      credits: 100,
      amount_eur_cents: 100,
      status: "future_provider_pending_state",
      checkout_session_id: sessionId,
      wallet: {
        balance: 125,
        paid_balance: 0,
        promotional_balance: 125,
        reversal_debt: 0,
        ai_spendable_balance: 0,
      },
    };
    window.history.replaceState(
      {},
      "",
      `/?checkout=success&session_id=${sessionId}`,
    );
    (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue(pendingStatus);

    render(<DashboardPage />);

    await act(async () => {
      await Promise.resolve();
      await jest.runAllTimersAsync();
    });

    expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(6);
    expect(screen.getByRole("status")).toHaveTextContent(
      "creditPurchasePendingRetry",
    );
    expect(
      screen.getByRole("button", { name: "creditPurchaseRetry" }),
    ).toBeInTheDocument();
    expect(window.location.search).toContain("session_id=cs_test_slow_pending");

    (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValueOnce({
      ...pendingStatus,
      status: "paid",
      wallet: {
        ...pendingStatus.wallet,
        balance: 225,
        paid_balance: 100,
        ai_spendable_balance: 100,
      },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "creditPurchaseRetry" }),
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(7);
    expect(screen.getByRole("status")).toHaveTextContent(
      "creditPurchaseSuccess",
    );
    expect(window.location.search).toBe("");
  });

  it("cancels delayed checkout polling when the dashboard unmounts", async () => {
    jest.useFakeTimers();
    const sessionId = "cs_test_unmounted_pending";
    window.history.replaceState(
      {},
      "",
      `/?checkout=success&session_id=${sessionId}`,
    );
    (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
      purchase_id: "purchase-unmounted",
      package_key: "starter",
      credits: 100,
      amount_eur_cents: 100,
      status: "awaiting_payment",
      checkout_session_id: sessionId,
      wallet: {
        balance: 125,
        paid_balance: 0,
        promotional_balance: 125,
        reversal_debt: 0,
        ai_spendable_balance: 0,
      },
    });

    const { unmount } = render(<DashboardPage />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);

    unmount();
    await act(async () => {
      await jest.runAllTimersAsync();
    });

    expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
    expect(window.location.search).toContain(
      "session_id=cs_test_unmounted_pending",
    );
  });

  it.each([
    ["failed", "creditPurchaseFailed"],
    ["expired", "creditPurchaseExpired"],
  ])(
    "shows a terminal notice when Stripe checkout is %s",
    async (status, expectedNotice) => {
      window.history.replaceState(
        {},
        "",
        `/?checkout=success&session_id=cs_test_${status}`,
      );
      (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
        purchase_id: `purchase-${status}`,
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status,
        checkout_session_id: `cs_test_${status}`,
        wallet: {
          balance: 100,
          paid_balance: 0,
          promotional_balance: 100,
          reversal_debt: 0,
          ai_spendable_balance: 0,
        },
      });

      render(<DashboardPage />);

      const notice = await screen.findByRole("status");
      await waitFor(() => {
        expect(notice).toHaveTextContent(expectedNotice);
      });
      expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
      expect(__setWalletMock).toHaveBeenCalledWith(
        expect.objectContaining({
          balance: 100,
        }),
      );
      expect(
        screen.queryByText("creditPurchasePending"),
      ).not.toBeInTheDocument();
      expect(window.location.search).toBe("");
    },
  );

  // REGRESSION: owner-reachable reversed and disputed purchases fell through
  // to the unknown-status path, which polled them forever as if they were
  // pending and retained stale checkout return parameters.
  it.each([
    [
      "reversed",
      "creditPurchaseReversed",
      {
        balance: 25,
        paid_balance: 0,
        promotional_balance: 25,
        reversal_debt: 0,
        ai_spendable_balance: 0,
      },
    ],
    [
      "disputed",
      "creditPurchaseDisputed",
      {
        balance: 0,
        paid_balance: 0,
        promotional_balance: 0,
        reversal_debt: 75,
        ai_spendable_balance: 0,
      },
    ],
  ])(
    "settles a %s checkout return without retrying or starting another purchase",
    async (status, expectedNotice, wallet) => {
      jest.useFakeTimers();
      const sessionId = `cs_test_${status}`;
      window.history.replaceState(
        {},
        "",
        `/?checkout=success&session_id=${sessionId}&campaign=beta#credits`,
      );
      (api.getCreditCheckoutStatus as jest.Mock).mockResolvedValue({
        purchase_id: `purchase-${status}`,
        package_key: "starter",
        credits: 100,
        amount_eur_cents: 100,
        status,
        checkout_session_id: sessionId,
        wallet,
      });

      render(<DashboardPage />);
      await act(async () => {
        await Promise.resolve();
      });

      expect(screen.getByRole("status")).toHaveTextContent(expectedNotice);
      expect(api.getCreditCheckoutStatus).toHaveBeenCalledTimes(1);
      expect(__setWalletMock).toHaveBeenCalledWith(wallet);
      expect(api.createCreditCheckout).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("button", { name: "creditPurchaseRetry" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("link", { name: "billingContractDownload" }),
      ).not.toBeInTheDocument();
      expect(window.location.search).toBe("?campaign=beta");
      expect(window.location.hash).toBe("#credits");
    },
  );
});
