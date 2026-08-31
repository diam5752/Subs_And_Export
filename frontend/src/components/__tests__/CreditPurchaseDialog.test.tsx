import React, { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  CreditPurchaseDialog,
  isAllowedStripeCheckoutUrl,
} from "@/components/CreditPurchaseDialog";
import { api } from "@/lib/api";
import {
  acceptConsumerTerms,
  catalog,
  consumerContract,
  mockLocaleState,
  mockPaidCreditLegalPublication,
  resetCreditPurchaseDialogMocks,
  restorePaidCreditUiReview,
} from "../../../test-support/creditPurchaseDialogTestSupport";

jest.mock("@/lib/paidCreditLegal", () => ({
  paidCreditLegalPublicationIsApproved: () =>
    mockPaidCreditLegalPublication.approved,
}));

jest.mock("@/lib/api", () => ({
  api: {
    getCreditCatalog: jest.fn(),
    createCreditCheckout: jest.fn(),
  },
}));

jest.mock("@/context/I18nContext", () => {
  const translate = (key: string, values?: Record<string, string | number>) =>
    values ? `${key}:${JSON.stringify(values)}` : key;
  return {
    useI18n: () => ({ locale: mockLocaleState.locale, t: translate }),
  };
});

jest.mock("@/context/PointsContext", () => ({
  usePoints: () => ({
    balance: 35,
    paidBalance: 20,
    promotionalBalance: 15,
    reversalDebt: 0,
    aiSpendableBalance: 20,
    isLoading: false,
    error: null,
    refreshBalance: jest.fn(),
    setBalance: jest.fn(),
    setWallet: jest.fn(),
  }),
}));

function FocusHarness() {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>
        Launch purchase
      </button>
      <CreditPurchaseDialog
        isOpen={isOpen}
        isAuthenticated
        onClose={() => setIsOpen(false)}
        onRequireAuth={jest.fn()}
      />
    </>
  );
}

describe("CreditPurchaseDialog", () => {
  const onClose = jest.fn();
  const onRequireAuth = jest.fn();
  const onRedirect = jest.fn();

  beforeEach(() => resetCreditPurchaseDialogMocks(api));

  it("locks the root and body scrollers for mobile WebKit", () => {
    const scrollTo = jest.fn();
    Object.defineProperty(window, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });
    Object.defineProperty(window, "scrollX", { configurable: true, value: 0 });
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      value: 220,
    });

    const view = render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
      />,
    );

    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.body.style.position).toBe("fixed");
    expect(document.body.style.top).toBe("-220px");

    view.unmount();
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(document.body.style.position).toBe("");
    expect(scrollTo).toHaveBeenCalledWith(0, 220);
  });

  afterAll(restorePaidCreditUiReview);

  it("accepts only the exact Stripe hosted-checkout origin", () => {
    expect(
      isAllowedStripeCheckoutUrl(
        "https://checkout.stripe.com/c/pay/cs_test_123",
      ),
    ).toBe(true);
    expect(
      isAllowedStripeCheckoutUrl("http://checkout.stripe.com/c/pay/test"),
    ).toBe(false);
    expect(
      isAllowedStripeCheckoutUrl(
        "https://checkout.stripe.com.evil.example/test",
      ),
    ).toBe(false);
    expect(
      isAllowedStripeCheckoutUrl(
        "https://checkout.stripe.com@evil.example/test",
      ),
    ).toBe(false);
    expect(isAllowedStripeCheckoutUrl("javascript:alert(1)")).toBe(false);
    expect(isAllowedStripeCheckoutUrl("not a URL")).toBe(false);
  });

  it("recommends the smallest sufficient package and starts one hosted checkout", async () => {
    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        requiredCredits={60}
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    const starter = await screen.findByRole("radio", { name: /starter/i });
    expect(starter).toBeChecked();
    expect(screen.getByText(/creditPurchaseMissing/)).toHaveTextContent("40");

    acceptConsumerTerms();
    fireEvent.click(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    );

    await waitFor(() => {
      expect(api.createCreditCheckout).toHaveBeenCalledWith(
        "starter",
        expect.stringMatching(/^checkout-/),
        "video-credits-v1",
        "GR",
        {
          disclosure_id: "gsubs-b2c-el-v1",
          disclosure_sha256: "a".repeat(64),
          locale: "el",
          policy_version: "policy-v1",
          terms_version: "terms-v1",
          withdrawal_notice_version: "withdrawal-v1",
          terms_accepted: true,
          immediate_performance_requested: true,
          withdrawal_consequences_acknowledged: true,
        },
      );
      expect(onRedirect).toHaveBeenCalledWith(
        "https://checkout.stripe.com/c/pay/cs_test_123",
      );
    });
    expect(onRequireAuth).not.toHaveBeenCalled();
  });

  it("requires login before creating a checkout for an anonymous user", async () => {
    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated={false}
        requiredCredits={30}
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    await screen.findByRole("radio", { name: /starter/i });
    fireEvent.click(
      screen.getByRole("button", { name: "creditPurchaseSignIn" }),
    );

    expect(onRequireAuth).toHaveBeenCalledTimes(1);
    expect(api.createCreditCheckout).not.toHaveBeenCalled();
    expect(onRedirect).not.toHaveBeenCalled();
  });

  it("supports Escape, backdrop closing, and explicit package selection", async () => {
    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    const creator = await screen.findByRole("radio", { name: /creator/i });
    fireEvent.click(creator);
    expect(creator).toBeChecked();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("credit-purchase-dialog"));
    expect(onClose).toHaveBeenCalledTimes(2);

    acceptConsumerTerms();
    fireEvent.click(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    );

    await waitFor(() => {
      expect(api.createCreditCheckout).toHaveBeenCalledWith(
        "creator",
        expect.stringMatching(/^checkout-/),
        "video-credits-v1",
        "GR",
        expect.objectContaining({
          terms_accepted: true,
          immediate_performance_requested: true,
          withdrawal_consequences_acknowledged: true,
        }),
      );
    });
  });

  // REGRESSION: custom role=radio buttons did not implement the keyboard
  // interaction required for a single-select radio group.
  it("uses native radios with wrapping arrow and Home/End navigation", async () => {
    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    const starter = await screen.findByRole("radio", { name: /starter/i });
    const creator = screen.getByRole("radio", { name: /creator/i });
    const studio = screen.getByRole("radio", { name: /studio/i });
    [starter, creator, studio].forEach((radio) => {
      expect(radio).toHaveAttribute("type", "radio");
      expect(radio).toHaveAttribute("name", "credit-package");
    });

    starter.focus();
    fireEvent.keyDown(starter, { key: "ArrowRight" });
    expect(creator).toBeChecked();
    await waitFor(() => expect(creator).toHaveFocus());

    fireEvent.keyDown(creator, { key: "End" });
    expect(studio).toBeChecked();
    await waitFor(() => expect(studio).toHaveFocus());

    fireEvent.keyDown(studio, { key: "ArrowRight" });
    expect(starter).toBeChecked();
    await waitFor(() => expect(starter).toHaveFocus());
  });

  // REGRESSION: keyboard focus could leave the modal, and closing did not
  // restore focus to the control that opened it.
  it("traps focus, focuses the close control, and restores the opener", async () => {
    render(<FocusHarness />);

    const trigger = screen.getByRole("button", {
      name: "Launch purchase",
    });
    trigger.focus();
    fireEvent.click(trigger);

    const closeButton = screen.getByRole("button", { name: "closeLabel" });
    await waitFor(() => expect(closeButton).toHaveFocus());
    await screen.findByRole("radio", { name: /starter/i });
    const lastDisclosureControl = screen.getByText(
      "creditPurchaseExactConsentDetails",
    );

    lastDisclosureControl.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(closeButton).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(lastDisclosureControl).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("surfaces a non-Error catalog failure without offering checkout", async () => {
    (api.getCreditCatalog as jest.Mock).mockRejectedValueOnce(
      "catalog unavailable",
    );

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "creditPurchaseLoadError",
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /creditPurchase(?:ContinueToPayment|Continue|SignIn)/,
      }),
    ).not.toBeInTheDocument();
    expect(api.createCreditCheckout).not.toHaveBeenCalled();
  });

  it("never follows a checkout URL that fails the allow-list", async () => {
    (api.createCreditCheckout as jest.Mock).mockResolvedValueOnce({
      purchase_id: "purchase-1",
      checkout_session_id: "cs_test_123",
      checkout_url: "https://checkout.stripe.com.evil.example/cs_test_123",
      status: "pending",
    });

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    await screen.findByRole("radio", { name: /starter/i });
    acceptConsumerTerms();
    fireEvent.click(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "creditPurchaseUnsafeRedirect",
    );
    expect(onRedirect).not.toHaveBeenCalled();
  });

  it("fails closed when the server reports that checkout is disabled", async () => {
    (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
      ...catalog,
      checkout_enabled: false,
    });

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "creditPurchaseNotEnabled",
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByText("€1.00")).not.toBeInTheDocument();
    expect(screen.queryByText("€3.00")).not.toBeInTheDocument();
    expect(screen.queryByText("€10.00")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /creditPurchase(?:ContinueToPayment|Continue|SignIn)/,
      }),
    ).not.toBeInTheDocument();
    expect(api.createCreditCheckout).not.toHaveBeenCalled();
  });

  it("shows the customer-facing purchase UI in safe local review mode", async () => {
    // REGRESSION: local design review showed internal preview messaging
    // instead of the exact interface an active customer will see.
    process.env.NEXT_PUBLIC_PAID_CREDITS_UI_REVIEW = "1";
    (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
      ...catalog,
      checkout_enabled: false,
    });

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    expect(
      await screen.findByRole("radio", { name: /starter/i }),
    ).toBeChecked();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(
      screen.queryByText("creditPurchaseDescription"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("credit-purchase-available-balance"),
    ).toHaveTextContent("20creditPurchaseAvailableNow");
    expect(
      screen.queryByText("creditPurchaseTotalBalance"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("creditPurchaseCloudBalance"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("creditPurchasePromoBalance"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("€1.00")).toBeVisible();
    expect(screen.getByText("€3.00")).toBeVisible();
    expect(screen.getByText("€10.00")).toBeVisible();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(
      screen.queryByText("creditPurchaseStripeNote"),
    ).not.toBeInTheDocument();

    const purchaseButton = screen.getByRole("button", {
      name: /creditPurchaseContinueToPayment/,
    });
    expect(purchaseButton).toBeDisabled();
    acceptConsumerTerms();
    expect(purchaseButton).toBeEnabled();
    fireEvent.click(purchaseButton);
    expect(api.createCreditCheckout).not.toHaveBeenCalled();
    expect(onRedirect).not.toHaveBeenCalled();
  });

  it("fails closed unless the backend publishes an exact Greece-only billing scope", async () => {
    (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
      ...catalog,
      billing_country_scope: ["GR", "CY"],
    });

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "creditPurchaseNotEnabled",
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(api.createCreditCheckout).not.toHaveBeenCalled();
  });

  it("does not present draft wording as operative terms", async () => {
    (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
      ...catalog,
      checkout_enabled: true,
      consumer_contract: {
        ...consumerContract,
        status: "draft_unapproved",
      },
    });

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "creditPurchaseNotEnabled",
    );
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(
      screen.queryByText(consumerContract.content.service_description),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByText("€1.00")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /creditPurchase(?:Continue|Pay|SignIn)/,
      }),
    ).not.toBeInTheDocument();
    expect(api.createCreditCheckout).not.toHaveBeenCalled();
  });

  it("also fails closed when frontend legal publication is unapproved", async () => {
    mockPaidCreditLegalPublication.approved = false;

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "creditPurchaseNotEnabled",
    );
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByText("€1.00")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /creditPurchase(?:Continue|Pay|SignIn)/,
      }),
    ).not.toBeInTheDocument();
  });

  it("also fails closed when the backend approval status disagrees with the contract", async () => {
    (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
      ...catalog,
      consumer_contract_status: "unavailable_unapproved",
    });

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "creditPurchaseNotEnabled",
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByText("€1.00")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(api.createCreditCheckout).not.toHaveBeenCalled();
  });

  it("fails closed when the returned disclosure locale does not match the request", async () => {
    (api.getCreditCatalog as jest.Mock).mockResolvedValueOnce({
      ...catalog,
      consumer_contract: {
        ...consumerContract,
        locale: "en",
      },
    });

    render(
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "creditPurchaseNotEnabled",
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(api.createCreditCheckout).not.toHaveBeenCalled();
  });
});
