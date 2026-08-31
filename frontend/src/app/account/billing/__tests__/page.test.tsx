import React, { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import BillingAccountPage from "@/app/account/billing/page";
import { api, type BillingPurchaseResponse } from "@/lib/api";

const mockUseAuth = jest.fn();
const mockPaidCreditLegalPublicationIsApproved = jest.fn();
const mockTranslate = (
  key: string,
  values?: Record<string, string | number>,
) => {
  const messages: Record<string, string> = {
    billingArtifactError: "The artifact could not be downloaded.",
    billingContractDownload: "Download contract confirmation",
    billingPageEmpty: "No billing purchases yet.",
    billingPageLoadError: "Purchases could not be loaded.",
    billingPageSignIn: "Sign in to see your purchases.",
    billingWithdrawalCancel: "Cancel withdrawal",
    billingWithdrawalConfirm: "Confirm withdrawal",
    billingWithdrawalConcludedAt: "Contract concluded",
    billingWithdrawalDownload: "Download withdrawal acknowledgement",
    billingWithdrawalResolutionDownload: "Download final decision",
    billingWithdrawalAccepted: "Withdrawal accepted and refunded",
    billingWithdrawalRejected: "Withdrawal reviewed and rejected",
    billingWithdrawalEmail: "Email for confirmation",
    billingWithdrawalError: "The withdrawal could not be submitted.",
    billingWithdrawalName: "Consumer name",
    billingWithdrawalPackage: "Package",
    billingWithdrawalPending: "Withdrawal pending manual review",
    billingWithdrawalPurchaseId: "Purchase identifier",
    billingWithdrawalStart: "Withdraw from the contract here",
    billingWithdrawalUnavailable:
      "Electronic submission is currently unavailable.",
    billingWithdrawalStatement:
      "I give notice that I withdraw from the GSUBS credit " +
      "purchase contract identified by {purchaseId}.",
    creditPurchaseWithdrawalFormLink: "Read the withdrawal terms",
    loginSubmit: "Sign in",
  };
  return (messages[key] ?? key).replace(/\{(\w+)\}/g, (_match, name: string) =>
    String(values?.[name] ?? ""),
  );
};

jest.mock("@/lib/api", () => ({
  api: {
    listBillingPurchases: jest.fn(),
    submitBillingWithdrawal: jest.fn(),
    downloadBillingArtifact: jest.fn(),
  },
}));

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("@/context/I18nContext", () => ({
  useI18n: () => ({
    locale: "en",
    t: mockTranslate,
  }),
}));

jest.mock("@/lib/paidCreditLegal", () => ({
  paidCreditLegalPublicationIsApproved: () =>
    mockPaidCreditLegalPublicationIsApproved(),
}));

const eligiblePurchase: BillingPurchaseResponse = {
  purchase_id: "a".repeat(32),
  package_key: "starter",
  credits: 100,
  amount_eur_cents: 100,
  currency: "eur",
  status: "paid",
  created_at: 1_800_000_000,
  fulfilled_at: 1_800_000_001,
  contract_confirmation_available: true,
  contract_confirmation_url: `/billing/purchases/${"a".repeat(32)}/contract-confirmation`,
  contract_concluded_at: 1_800_000_001,
  withdrawal_action_available: true,
  withdrawal_status: null,
  withdrawal_acknowledgement_available: false,
  withdrawal_acknowledgement_url: null,
  withdrawal_resolution_available: false,
  withdrawal_resolution_decision: null,
  withdrawal_resolution_url: null,
};

const withdrawalResponse = {
  withdrawal_id: "b".repeat(32),
  purchase_id: eligiblePurchase.purchase_id,
  status: "pending_manual_review",
  submitted_at: 1_800_000_100,
  timeliness_assessment_status: "pending_manual_review",
  acknowledgement_sha256: "c".repeat(64),
  acknowledgement_url:
    `/billing/purchases/${eligiblePurchase.purchase_id}/` +
    "withdrawal-acknowledgement",
};

function signedInAuth() {
  return {
    user: {
      id: "user-1",
      name: "Test Consumer",
      email: "consumer@example.com",
    },
    isLoading: false,
  };
}

async function openWithdrawalForm() {
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Withdraw from the contract here",
    }),
  );
  return screen
    .getByRole("button", { name: "Confirm withdrawal" })
    .closest("form") as HTMLFormElement;
}

describe("BillingAccountPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseAuth.mockReturnValue(signedInAuth());
    mockPaidCreditLegalPublicationIsApproved.mockReturnValue(false);
    (api.listBillingPurchases as jest.Mock).mockResolvedValue([
      eligiblePurchase,
    ]);
    (api.submitBillingWithdrawal as jest.Mock).mockResolvedValue(
      withdrawalResponse,
    );
  });

  it("waits for authentication before requesting billing records", () => {
    mockUseAuth.mockReturnValue({
      user: null,
      isLoading: true,
    });

    const { container } = render(<BillingAccountPage />);

    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
    expect(api.listBillingPurchases).not.toHaveBeenCalled();
  });

  it("shows a sign-in action without making an authenticated request", async () => {
    mockUseAuth.mockReturnValue({
      user: null,
      isLoading: false,
    });

    render(<BillingAccountPage />);

    expect(
      await screen.findByText("Sign in to see your purchases."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(api.listBillingPurchases).not.toHaveBeenCalled();
  });

  it("shows the authenticated empty state", async () => {
    (api.listBillingPurchases as jest.Mock).mockResolvedValue([]);

    render(<BillingAccountPage />);

    expect(
      await screen.findByText("No billing purchases yet."),
    ).toBeInTheDocument();
  });

  it.each([
    [new Error("Billing vault unavailable"), "Billing vault unavailable"],
    [{ reason: "unexpected" }, "Purchases could not be loaded."],
  ])("reports purchase-loading failures safely", async (failure, message) => {
    (api.listBillingPurchases as jest.Mock).mockRejectedValue(failure);

    render(<BillingAccountPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("downloads the immutable contract artifact with a deterministic filename", async () => {
    const artifact = new Blob(["contract"], { type: "application/json" });
    const createObjectURL = jest.fn(() => "blob:contract");
    const revokeObjectURL = jest.fn();
    let clickedDownload = "";
    let clickedHref = "";
    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURL,
    });
    const clickSpy = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function click(this: HTMLAnchorElement) {
        clickedDownload = this.download;
        clickedHref = this.href;
      });
    (api.downloadBillingArtifact as jest.Mock).mockResolvedValue(artifact);

    render(<BillingAccountPage />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Download contract confirmation",
      }),
    );

    await waitFor(() => {
      expect(api.downloadBillingArtifact).toHaveBeenCalledWith(
        eligiblePurchase.contract_confirmation_url,
      );
    });
    expect(createObjectURL).toHaveBeenCalledWith(artifact);
    expect(clickedDownload).toBe(
      `gsubs-contract-${eligiblePurchase.purchase_id}.json`,
    );
    expect(clickedHref).toBe("blob:contract");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:contract");
    expect(
      document.querySelector('a[download^="gsubs-contract-"]'),
    ).not.toBeInTheDocument();

    clickSpy.mockRestore();
  });

  it("downloads an available withdrawal acknowledgement", async () => {
    const acknowledgementUrl =
      `/billing/purchases/${eligiblePurchase.purchase_id}/` +
      "withdrawal-acknowledgement";
    (api.listBillingPurchases as jest.Mock).mockResolvedValue([
      {
        ...eligiblePurchase,
        withdrawal_action_available: false,
        withdrawal_status: "pending_manual_review",
        withdrawal_acknowledgement_available: true,
        withdrawal_acknowledgement_url: acknowledgementUrl,
      },
    ]);
    (api.downloadBillingArtifact as jest.Mock).mockResolvedValue(
      new Blob(["acknowledgement"]),
    );
    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: jest.fn(() => "blob:withdrawal"),
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: jest.fn(),
    });
    const clickSpy = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    render(<BillingAccountPage />);

    expect(
      await screen.findByText("Withdrawal pending manual review"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Download withdrawal acknowledgement",
      }),
    );
    await waitFor(() => {
      expect(api.downloadBillingArtifact).toHaveBeenCalledWith(
        acknowledgementUrl,
      );
    });

    clickSpy.mockRestore();
  });

  it.each([
    ["accepted_refunded", "Withdrawal accepted and refunded"],
    ["rejected", "Withdrawal reviewed and rejected"],
  ])(
    "shows and downloads the immutable %s resolution",
    async (decision, expectedMessage) => {
      const resolutionUrl =
        `/billing/purchases/${eligiblePurchase.purchase_id}/` +
        "withdrawal-resolution";
      (api.listBillingPurchases as jest.Mock).mockResolvedValue([
        {
          ...eligiblePurchase,
          withdrawal_action_available: false,
          withdrawal_status: decision,
          withdrawal_acknowledgement_available: true,
          withdrawal_acknowledgement_url:
            `/billing/purchases/` +
            `${eligiblePurchase.purchase_id}/` +
            "withdrawal-acknowledgement",
          withdrawal_resolution_available: true,
          withdrawal_resolution_decision: decision,
          withdrawal_resolution_url: resolutionUrl,
        },
      ]);
      (api.downloadBillingArtifact as jest.Mock).mockResolvedValue(
        new Blob(["resolution"]),
      );
      Object.defineProperty(window.URL, "createObjectURL", {
        configurable: true,
        value: jest.fn(() => "blob:resolution"),
      });
      Object.defineProperty(window.URL, "revokeObjectURL", {
        configurable: true,
        value: jest.fn(),
      });
      const clickSpy = jest
        .spyOn(HTMLAnchorElement.prototype, "click")
        .mockImplementation(() => undefined);

      render(<BillingAccountPage />);

      expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", {
          name: "Download final decision",
        }),
      );
      await waitFor(() => {
        expect(api.downloadBillingArtifact).toHaveBeenCalledWith(resolutionUrl);
      });

      clickSpy.mockRestore();
    },
  );

  it.each([
    [new Error("Artifact vault unavailable"), "Artifact vault unavailable"],
    [{ reason: "unexpected" }, "The artifact could not be downloaded."],
  ])("reports artifact download failures safely", async (failure, message) => {
    (api.downloadBillingArtifact as jest.Mock).mockRejectedValue(failure);

    render(<BillingAccountPage />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Download contract confirmation",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("allows a consumer to review, edit, and cancel a withdrawal", async () => {
    render(<BillingAccountPage />);

    const startButton = await screen.findByRole("button", {
      name: "Withdraw from the contract here",
    });
    startButton.focus();
    await openWithdrawalForm();
    await waitFor(() => {
      expect(screen.getByLabelText("Consumer name")).toHaveFocus();
    });
    expect(
      screen.getByText(
        `I give notice that I withdraw from the GSUBS credit purchase contract identified by ${eligiblePurchase.purchase_id}.`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Contract concluded")).toBeInTheDocument();
    expect(screen.getByLabelText("Consumer name")).toHaveValue("Test Consumer");
    expect(screen.getByLabelText("Email for confirmation")).toHaveValue(
      "consumer@example.com",
    );

    fireEvent.change(screen.getByLabelText("Consumer name"), {
      target: { value: "Updated Consumer" },
    });
    fireEvent.change(screen.getByLabelText("Email for confirmation"), {
      target: { value: "updated@example.com" },
    });
    expect(screen.getByLabelText("Consumer name")).toHaveValue(
      "Updated Consumer",
    );
    expect(screen.getByLabelText("Email for confirmation")).toHaveValue(
      "updated@example.com",
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Cancel withdrawal",
      }),
    );
    expect(screen.queryByLabelText("Consumer name")).not.toBeInTheDocument();
    const restoredStartButton = screen.getByRole("button", {
      name: "Withdraw from the contract here",
    });
    await waitFor(() => expect(restoredStartButton).toHaveFocus());
    expect(api.submitBillingWithdrawal).not.toHaveBeenCalled();
  });

  it("submits a withdrawal once, disables the form, and reloads the vault", async () => {
    let resolveWithdrawal: (response: typeof withdrawalResponse) => void = () =>
      undefined;
    (api.submitBillingWithdrawal as jest.Mock).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveWithdrawal = resolve;
        }),
    );

    render(<BillingAccountPage />);
    const form = await openWithdrawalForm();
    fireEvent.change(screen.getByLabelText("Consumer name"), {
      target: { value: "Updated Consumer" },
    });
    fireEvent.change(screen.getByLabelText("Email for confirmation"), {
      target: { value: "updated@example.com" },
    });

    fireEvent.submit(form);
    await waitFor(() => {
      expect(api.submitBillingWithdrawal).toHaveBeenCalledWith(
        eligiblePurchase.purchase_id,
        {
          locale: "en",
          withdrawal_requested: true,
          confirmed_name: "Updated Consumer",
          confirmation_email: "updated@example.com",
        },
        expect.stringMatching(/^withdrawal-/),
      );
    });
    expect(
      screen.getByRole("button", {
        name: "Confirm withdrawal",
      }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Cancel withdrawal",
      }),
    ).toBeDisabled();

    await act(async () => {
      resolveWithdrawal(withdrawalResponse);
    });

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Withdrawal pending manual review",
    );
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveFocus();
    });
    await waitFor(() => {
      expect(api.listBillingPurchases).toHaveBeenCalledTimes(2);
    });
  });

  it.each([
    [
      new Error("Withdrawal service unavailable"),
      "Withdrawal service unavailable",
    ],
    [{ reason: "unexpected" }, "The withdrawal could not be submitted."],
  ])(
    "keeps the form open and reports withdrawal failures",
    async (failure, message) => {
      (api.submitBillingWithdrawal as jest.Mock).mockRejectedValue(failure);

      render(<BillingAccountPage />);
      const form = await openWithdrawalForm();
      fireEvent.submit(form);

      expect(await screen.findByRole("alert")).toHaveTextContent(message);
      expect(screen.getByLabelText("Consumer name")).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: "Confirm withdrawal",
        }),
      ).not.toBeDisabled();
    },
  );

  it("renders an unknown conclusion time explicitly in the confirmation form", async () => {
    (api.listBillingPurchases as jest.Mock).mockResolvedValue([
      {
        ...eligiblePurchase,
        contract_concluded_at: null,
      },
    ]);

    render(<BillingAccountPage />);
    await openWithdrawalForm();

    expect(screen.getByText("—")).toBeInTheDocument();
  });

  // REGRESSION: a server-side availability failure must never be presented as
  // a computed legal deadline or an expired withdrawal window.
  it("reports electronic-route unavailability without claiming expiry", async () => {
    (api.listBillingPurchases as jest.Mock).mockResolvedValue([
      {
        ...eligiblePurchase,
        withdrawal_action_available: false,
      },
    ]);

    render(<BillingAccountPage />);

    expect(
      await screen.findByText(
        "Electronic submission is currently unavailable.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/expired|window|14.day/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Withdraw from the contract here",
      }),
    ).not.toBeInTheDocument();
  });

  it("reports a record without a concluded contract without deadline claims", async () => {
    (api.listBillingPurchases as jest.Mock).mockResolvedValue([
      {
        ...eligiblePurchase,
        status: "failed",
        fulfilled_at: null,
        contract_confirmation_available: false,
        contract_confirmation_url: null,
        contract_concluded_at: null,
        withdrawal_action_available: false,
      },
    ]);

    render(<BillingAccountPage />);

    expect(
      await screen.findByText("billingContractNotConcluded"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/expired|window|14.day/i),
    ).not.toBeInTheDocument();
  });

  it("links to approved published withdrawal terms", async () => {
    mockPaidCreditLegalPublicationIsApproved.mockReturnValue(true);
    (api.listBillingPurchases as jest.Mock).mockResolvedValue([]);

    render(<BillingAccountPage />);

    expect(
      await screen.findByRole("link", {
        name: "Read the withdrawal terms",
      }),
    ).toHaveAttribute("href", "/terms#withdrawal");
  });
});
