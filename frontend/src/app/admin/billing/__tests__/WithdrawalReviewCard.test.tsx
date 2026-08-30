import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WithdrawalReviewCard } from "@/app/admin/billing/WithdrawalReviewCard";
import {
  api,
  type BillingAdminPendingWithdrawal,
  type BillingWithdrawalResolutionResponse,
} from "@/lib/api";

jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    api: {
      resolveBillingWithdrawal: jest.fn(),
    },
  };
});

jest.mock("@/context/I18nContext", () => ({
  useI18n: () => ({
    locale: "en",
    t: (key: string) => key,
  }),
}));

const resolveWithdrawal = api.resolveBillingWithdrawal as jest.MockedFunction<
  typeof api.resolveBillingWithdrawal
>;
const WITHDRAWAL_ID = "1".repeat(32);
const PURCHASE_ID = "2".repeat(32);
const ADJUSTMENT_ID = "3".repeat(32);
const EXPLANATION =
  "The request was reviewed manually and the refund is complete.";

function withdrawalReview(
  withAdjustment: boolean,
): BillingAdminPendingWithdrawal {
  return {
    withdrawal_id: WITHDRAWAL_ID,
    purchase_id: PURCHASE_ID,
    locale: "en",
    submitted_at: 1_800_000_100,
    contract_concluded_at: 1_800_000_000,
    confirmed_name: "Test Consumer",
    confirmation_email: "consumer@example.com",
    available_adjustments: withAdjustment
      ? [
          {
            adjustment_id: ADJUSTMENT_ID,
            stripe_refund_id: "re_completed_manual_refund",
            amount_cents: 100,
            currency: "eur",
            aade_document_type: "11.4",
            aade_series: "RET-2026",
            aade_aa: "8",
            aade_mark: "223456789012345678",
            issued_at: 1_800_000_200,
          },
        ]
      : [],
  };
}

function resolution(
  decision: "accepted_refunded" | "rejected",
): BillingWithdrawalResolutionResponse {
  return {
    resolution_id: "4".repeat(32),
    withdrawal_id: WITHDRAWAL_ID,
    purchase_id: PURCHASE_ID,
    decision,
    reason_code:
      decision === "accepted_refunded"
        ? "statutory_right_accepted"
        : "request_not_eligible",
    adjustment_id: decision === "accepted_refunded" ? ADJUSTMENT_ID : null,
    resolved_at: 1_800_000_300,
    resolution_sha256: "5".repeat(64),
    resolution_url: `/billing/purchases/${PURCHASE_ID}/withdrawal-resolution`,
  };
}

describe("WithdrawalReviewCard", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("keeps acceptance disabled until refund and AADE evidence exist", () => {
    render(
      <WithdrawalReviewCard
        review={withdrawalReview(false)}
        onResolved={jest.fn()}
      />,
    );

    expect(
      screen.getByRole("radio", {
        name: /adminBillingWithdrawalAccept/,
      }),
    ).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "adminBillingWithdrawalNeedsRefundEvidence",
    );
    expect(
      screen.getByRole("radio", {
        name: /adminBillingWithdrawalReject/,
      }),
    ).not.toBeDisabled();
  });

  it("accepts only with linked completed manual evidence", async () => {
    const onResolved = jest.fn();
    const result = resolution("accepted_refunded");
    resolveWithdrawal.mockResolvedValueOnce(result);
    render(
      <WithdrawalReviewCard
        review={withdrawalReview(true)}
        onResolved={onResolved}
      />,
    );
    fireEvent.click(
      screen.getByRole("radio", {
        name: /adminBillingWithdrawalAccept/,
      }),
    );
    fireEvent.change(
      screen.getByLabelText("adminBillingWithdrawalAdjustmentEvidence"),
      {
        target: { value: ADJUSTMENT_ID },
      },
    );
    fireEvent.change(
      screen.getByLabelText("adminBillingWithdrawalCustomerExplanation"),
      {
        target: { value: EXPLANATION },
      },
    );
    fireEvent.click(
      screen.getByLabelText("adminBillingFinalWithdrawalReviewConfirm"),
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "adminBillingResolveWithdrawal",
      }),
    );

    await waitFor(() => {
      expect(resolveWithdrawal).toHaveBeenCalledTimes(1);
    });
    expect(resolveWithdrawal).toHaveBeenCalledWith(WITHDRAWAL_ID, {
      decision: "accepted_refunded",
      adjustment_id: ADJUSTMENT_ID,
      customer_explanation: EXPLANATION,
      final_manual_review_confirmed: true,
    });
    expect(onResolved).toHaveBeenCalledWith(result);
  });

  it("records rejection without claiming any money or tax action", async () => {
    const onResolved = jest.fn();
    const result = resolution("rejected");
    resolveWithdrawal.mockResolvedValueOnce(result);
    render(
      <WithdrawalReviewCard
        review={withdrawalReview(false)}
        onResolved={onResolved}
      />,
    );
    fireEvent.click(
      screen.getByRole("radio", {
        name: /adminBillingWithdrawalReject/,
      }),
    );
    fireEvent.change(
      screen.getByLabelText("adminBillingWithdrawalCustomerExplanation"),
      {
        target: {
          value:
            "The request was reviewed and is not eligible for " +
            "a mandatory refund.",
        },
      },
    );
    fireEvent.click(
      screen.getByLabelText("adminBillingFinalWithdrawalReviewConfirm"),
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "adminBillingResolveWithdrawal",
      }),
    );

    await waitFor(() => {
      expect(resolveWithdrawal).toHaveBeenCalledTimes(1);
    });
    expect(resolveWithdrawal).toHaveBeenCalledWith(
      WITHDRAWAL_ID,
      expect.objectContaining({
        decision: "rejected",
        adjustment_id: null,
      }),
    );
    expect(onResolved).toHaveBeenCalledWith(result);
  });

  it("requires a final choice, explanation, confirmation and never retries", async () => {
    resolveWithdrawal.mockRejectedValueOnce(new Error("Response lost"));
    render(
      <WithdrawalReviewCard
        review={withdrawalReview(false)}
        onResolved={jest.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "adminBillingResolveWithdrawal",
      }),
    );
    expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
    expect(resolveWithdrawal).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("radio", {
        name: /adminBillingWithdrawalReject/,
      }),
    );
    fireEvent.change(
      screen.getByLabelText("adminBillingWithdrawalCustomerExplanation"),
      {
        target: { value: EXPLANATION },
      },
    );
    fireEvent.click(
      screen.getByLabelText("adminBillingFinalWithdrawalReviewConfirm"),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "adminBillingResolveWithdrawal",
      }),
    );

    expect(
      await screen.findByText("adminBillingWithdrawalResolveError"),
    ).toBeInTheDocument();
    expect(resolveWithdrawal).toHaveBeenCalledTimes(1);
    await Promise.resolve();
    await Promise.resolve();
    expect(resolveWithdrawal).toHaveBeenCalledTimes(1);
  });
});
