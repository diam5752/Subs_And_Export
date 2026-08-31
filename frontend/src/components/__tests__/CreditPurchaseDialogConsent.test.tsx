import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import { CreditPurchaseDialog } from "@/components/CreditPurchaseDialog";
import { api, type CreditCatalogResponse } from "@/lib/api";
import {
  acceptConsumerTerms,
  catalog,
  consumerContract,
  deferred,
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

describe("CreditPurchaseDialog consent lifecycle", () => {
  const onClose = jest.fn();
  const onRequireAuth = jest.fn();
  const onRedirect = jest.fn();

  beforeEach(() => resetCreditPurchaseDialogMocks(api));
  afterAll(restorePaidCreditUiReview);

  it("requires one explicit combined acceptance and does not let legal links toggle it", async () => {
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
    const checkbox = screen.getByRole("checkbox", {
      name: "creditPurchaseConsentRequest",
    });
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(checkbox).not.toBeChecked();
    expect(checkbox).toHaveAccessibleDescription(
      "creditPurchaseConsentConsequence",
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "creditPurchaseBillingScope",
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "creditPurchaseVatIncluded",
    );
    expect(screen.getByRole("note")).toHaveTextContent("creditPurchaseOneOff");

    fireEvent.click(
      screen.getByRole("link", { name: "creditPurchaseTermsLink" }),
    );
    expect(checkbox).not.toBeChecked();
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).toBeDisabled();

    fireEvent.click(screen.getByText("creditPurchaseExactConsentDetails"));
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).toBeEnabled();
  });

  // REGRESSION: the complete contract made the purchase decision unreadable.
  // Keep the mandatory purchase essentials next to the CTA and route the full
  // pre-contract information to stable, anchored legal sections.
  it("keeps purchase essentials in the dialog and links the full disclosure elsewhere", async () => {
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

    expect(screen.getByRole("note")).toHaveTextContent(
      "creditPurchaseBillingScope",
    );
    expect(
      screen.getByRole("link", {
        name: "creditPurchaseTermsLink",
      }),
    ).toHaveAttribute("href", "/terms#seller");
    expect(
      screen.getByRole("link", {
        name: "creditPurchaseWithdrawalDetailsLink",
      }),
    ).toHaveAttribute("href", "/terms#withdrawal-rights");
    expect(screen.getByText("€1.00")).toBeVisible();
    expect(
      screen.getByRole("radio", {
        name: /starter/i,
      }),
    ).toHaveAccessibleName(/100/);
    // REGRESSION: the footer repeated the selected package and implied that
    // this pre-Stripe step placed the paid order.
    expect(
      screen.queryByText(/creditPurchaseOrderSummary/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment.*"amount":"1.00"/,
      }),
    ).toBeDisabled();
    expect(
      screen.queryByText(consumerContract.trader.legal_name),
    ).not.toBeInTheDocument();
    Object.values(consumerContract.content).forEach((content) => {
      expect(screen.queryByText(content)).not.toBeInTheDocument();
    });
    Object.values(consumerContract.required_acceptances).forEach(
      (acceptance) => {
        expect(screen.getByText(acceptance)).not.toBeVisible();
      },
    );
    fireEvent.click(screen.getByText("creditPurchaseExactConsentDetails"));
    Object.values(consumerContract.required_acceptances).forEach(
      (acceptance) => {
        expect(screen.getByText(acceptance)).toBeVisible();
      },
    );
  });

  it("clears every acceptance and rotates the intent when the package changes", async () => {
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
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).toBeEnabled();

    fireEvent.click(screen.getByRole("radio", { name: /creator/i }));

    screen.getAllByRole("checkbox").forEach((checkbox) => {
      expect(checkbox).not.toBeChecked();
    });
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).toBeDisabled();
  });

  // REGRESSION: a locale change could leave the previous disclosure and its
  // checked consent visible while a new catalog version was still loading.
  it("does not carry consent across a deferred locale and disclosure change", async () => {
    const greekCatalog = deferred<CreditCatalogResponse>();
    const englishCatalog = deferred<CreditCatalogResponse>();
    (api.getCreditCatalog as jest.Mock)
      .mockReset()
      .mockReturnValueOnce(greekCatalog.promise)
      .mockReturnValueOnce(englishCatalog.promise);

    const renderDialog = () => (
      <CreditPurchaseDialog
        isOpen
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />
    );
    const view = render(renderDialog());

    await act(async () => {
      greekCatalog.resolve(catalog);
    });
    await screen.findByRole("radio", { name: /starter/i });
    acceptConsumerTerms();
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).toBeEnabled();

    mockLocaleState.locale = "en";
    view.rerender(renderDialog());

    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(
      screen.queryByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).not.toBeInTheDocument();

    const changedCatalog = {
      ...catalog,
      consumer_contract: {
        ...consumerContract,
        disclosure_id: "gsubs-b2c-en-v2",
        disclosure_sha256: "b".repeat(64),
        locale: "en" as const,
        policy_version: "policy-v2",
        terms_version: "terms-v2",
        withdrawal_notice_version: "withdrawal-v2",
      },
    };
    await act(async () => {
      englishCatalog.resolve(changedCatalog);
    });

    await screen.findByRole("radio", { name: /starter/i });
    screen.getAllByRole("checkbox").forEach((checkbox) => {
      expect(checkbox).not.toBeChecked();
    });
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).toBeDisabled();

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
        expect.objectContaining({
          disclosure_id: "gsubs-b2c-en-v2",
          disclosure_sha256: "b".repeat(64),
          locale: "en",
          policy_version: "policy-v2",
          terms_version: "terms-v2",
          withdrawal_notice_version: "withdrawal-v2",
        }),
      );
    });
  });

  // REGRESSION: because the dialog stayed mounted, reopening could briefly
  // reveal the previous catalog and checked acceptance state before effects ran.
  it("starts every reopen with an empty, unaccepted loading state", async () => {
    const reopenedCatalog = deferred<CreditCatalogResponse>();
    (api.getCreditCatalog as jest.Mock)
      .mockReset()
      .mockResolvedValueOnce(catalog)
      .mockReturnValueOnce(reopenedCatalog.promise);

    const renderDialog = (isOpen: boolean) => (
      <CreditPurchaseDialog
        isOpen={isOpen}
        isAuthenticated
        onClose={onClose}
        onRequireAuth={onRequireAuth}
        onRedirect={onRedirect}
      />
    );
    const view = render(renderDialog(true));

    await screen.findByRole("radio", { name: /starter/i });
    acceptConsumerTerms();
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).toBeEnabled();

    view.rerender(renderDialog(false));
    view.rerender(renderDialog(true));

    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(
      screen.queryByText(consumerContract.content.service_description),
    ).not.toBeInTheDocument();

    await act(async () => {
      reopenedCatalog.resolve(catalog);
    });
    await screen.findByRole("radio", { name: /starter/i });
    screen.getAllByRole("checkbox").forEach((checkbox) => {
      expect(checkbox).not.toBeChecked();
    });
    expect(
      screen.getByRole("button", {
        name: /creditPurchaseContinueToPayment/,
      }),
    ).toBeDisabled();
  });
});
