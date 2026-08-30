import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { ManualRefundCard } from "@/app/admin/billing/ManualRefundCard";
import {
  api,
  type BillingAdminPendingInvoice,
  type BillingAdminPendingRefund,
  type RecordedManualRefundAccountingResponse,
} from "@/lib/api";

jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    api: {
      recordManualRefundAccounting: jest.fn(),
    },
  };
});

jest.mock("@/context/I18nContext", () => ({
  useI18n: () => ({
    locale: "en",
    t: (key: string) => key,
  }),
}));

const recordManualRefund =
  api.recordManualRefundAccounting as jest.MockedFunction<
    typeof api.recordManualRefundAccounting
  >;
const NOW = Date.parse("2026-02-15T10:00:00Z");
const PAYMENT_AT = Date.parse("2026-02-15T08:00:00Z") / 1000;
const REFUND_AT = Date.parse("2026-02-15T09:00:00Z") / 1000;
const ORIGINAL_ISSUED_AT = Date.parse("2026-02-15T08:30:00Z") / 1000;
const ADJUSTMENT_ISSUED_AT = Date.parse("2026-02-15T09:30:00Z") / 1000;
const ORIGINAL_MARK = "123456789012345678";
const ADJUSTMENT_MARK = "223456789012345678";

function originalInvoice(
  overrides: Partial<BillingAdminPendingInvoice> = {},
): BillingAdminPendingInvoice {
  return {
    invoice_id: "1".repeat(32),
    purchase_id: "2".repeat(32),
    document_status: "pending_manual_issue",
    purchase_status: "refunded",
    provider: "aade_etimologio",
    document_kind: "retail_service_receipt",
    refunded_amount_cents: 100,
    reversed_amount_cents: 100,
    reversed_credits: 100,
    dispute_active: false,
    requires_reversal_review: true,
    aade_document_type: null,
    aade_series: null,
    aade_aa: null,
    aade_mark: null,
    issued_at: null,
    recorded_at: null,
    created_at: PAYMENT_AT,
    financial_retention_until: 2_100_000_000,
    package: { key: "starter", credits: 100 },
    payment: {
      checkout_session_id: "cs_test_refund",
      payment_intent_id: "pi_test_refund",
      confirmed_at: PAYMENT_AT,
      livemode: false,
      amount_paid_cents: 100,
      currency: "eur",
      payment_status: "paid",
    },
    customer: {
      name: "Test Customer",
      email: "customer@example.com",
      country: "GR",
      city: "Athens",
      postal_code: "10558",
      line1: "Example 1",
      line2: null,
      state: "Attica",
      status: "ready_for_manual_issue",
      missing_required_fields: [],
    },
    tax: {
      gross_amount_cents: 100,
      net_amount_cents: 81,
      vat_amount_cents: 19,
      vat_rate_percent: 24,
    },
    service: { code: "4", name: "GSUBS Credits" },
    ...overrides,
  };
}

function refundReview(
  invoice: BillingAdminPendingInvoice = originalInvoice(),
): BillingAdminPendingRefund {
  return {
    reversal_id: "3".repeat(32),
    stripe_refund_id: "re_completed_manual_refund",
    stripe_refund_status: "succeeded",
    stripe_refund_created_at: REFUND_AT,
    amount_cents: 100,
    currency: "eur",
    linked_withdrawal_id: "4".repeat(32),
    original_invoice: invoice,
  };
}

function fillAdjustmentForm(): void {
  const adjustment = screen
    .getByText("adminBillingAdjustmentDocumentTitle")
    .closest("section");
  if (!adjustment) {
    throw new Error("Adjustment section was not rendered");
  }
  fireEvent.change(
    within(adjustment).getByLabelText("adminBillingDocumentType"),
    {
      target: { value: "11.4" },
    },
  );
  fireEvent.change(within(adjustment).getByLabelText("adminBillingSeries"), {
    target: { value: "RET-2026" },
  });
  fireEvent.change(within(adjustment).getByLabelText("adminBillingAa"), {
    target: { value: "8" },
  });
  fireEvent.change(within(adjustment).getByLabelText("adminBillingMark"), {
    target: { value: ADJUSTMENT_MARK },
  });
  fireEvent.change(
    within(adjustment).getByLabelText("adminBillingMarkRepeat"),
    {
      target: { value: ADJUSTMENT_MARK },
    },
  );
  fireEvent.change(within(adjustment).getByLabelText("adminBillingIssuedAt"), {
    target: { value: "2026-02-15T11:30" },
  });
}

describe("ManualRefundCard", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(Date, "now").mockReturnValue(NOW);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("starts with every adjustment identity field blank", () => {
    render(<ManualRefundCard review={refundReview()} onRecorded={jest.fn()} />);

    const adjustment = screen
      .getByText("adminBillingAdjustmentDocumentTitle")
      .closest("section");
    expect(adjustment).not.toBeNull();
    expect(
      within(adjustment as HTMLElement).getByLabelText(
        "adminBillingDocumentType",
      ),
    ).toHaveValue("");
    expect(
      within(adjustment as HTMLElement).getByLabelText("adminBillingSeries"),
    ).toHaveValue("");
    expect(
      within(adjustment as HTMLElement).getByLabelText("adminBillingAa"),
    ).toHaveValue("");
    expect(
      within(adjustment as HTMLElement).getByLabelText("adminBillingMark"),
    ).toHaveValue("");
    expect(
      within(adjustment as HTMLElement).getByLabelText("adminBillingIssuedAt"),
    ).toHaveValue("");
  });

  it("records exact existing Stripe and AADE evidence without defaults", async () => {
    const onRecorded = jest.fn();
    const result: RecordedManualRefundAccountingResponse = {
      adjustment_id: "5".repeat(32),
      purchase_id: "2".repeat(32),
      reversal_id: "3".repeat(32),
      stripe_refund_id: "re_completed_manual_refund",
      amount_cents: 100,
      currency: "eur",
      aade_document_type: "11.4",
      aade_series: "RET-2026",
      aade_aa: "8",
      aade_mark: ADJUSTMENT_MARK,
      issued_at: ADJUSTMENT_ISSUED_AT,
      recorded_at: ADJUSTMENT_ISSUED_AT + 60,
      financial_retention_until: 2_100_000_000,
      original_invoice_status: "issued",
      original_invoice_mark: ORIGINAL_MARK,
    };
    recordManualRefund.mockResolvedValueOnce(result);
    render(
      <ManualRefundCard review={refundReview()} onRecorded={onRecorded} />,
    );
    const original = screen
      .getByText("adminBillingOriginalDocumentTitle")
      .closest("section");
    if (!original) {
      throw new Error("Original section was not rendered");
    }
    fireEvent.change(within(original).getByLabelText("adminBillingAa"), {
      target: { value: "7" },
    });
    fireEvent.change(within(original).getByLabelText("adminBillingMark"), {
      target: { value: ORIGINAL_MARK },
    });
    fireEvent.change(
      within(original).getByLabelText("adminBillingMarkRepeat"),
      { target: { value: ORIGINAL_MARK } },
    );
    fireEvent.change(within(original).getByLabelText("adminBillingIssuedAt"), {
      target: { value: "2026-02-15T10:30" },
    });
    fillAdjustmentForm();
    fireEvent.click(
      screen.getByLabelText("adminBillingFinalRefundActionsConfirm"),
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "adminBillingRecordRefundEvidence",
      }),
    );

    await waitFor(() => {
      expect(recordManualRefund).toHaveBeenCalledTimes(1);
    });
    expect(recordManualRefund).toHaveBeenCalledWith("3".repeat(32), {
      original_document: {
        document_type: "11.2",
        series: "0",
        aa: "7",
        mark: ORIGINAL_MARK,
        issued_at: ORIGINAL_ISSUED_AT,
      },
      adjustment_document: {
        document_type: "11.4",
        series: "RET-2026",
        aa: "8",
        mark: ADJUSTMENT_MARK,
        issued_at: ADJUSTMENT_ISSUED_AT,
      },
      final_manual_actions_confirmed: true,
    });
    expect(onRecorded).toHaveBeenCalledWith(result);
  });

  it("requires the exact final confirmation and never retries a failed write", async () => {
    recordManualRefund.mockRejectedValueOnce(new Error("Response lost"));
    render(
      <ManualRefundCard
        review={refundReview(
          originalInvoice({
            document_status: "issued",
            aade_document_type: "11.2",
            aade_series: "0",
            aade_aa: "7",
            aade_mark: ORIGINAL_MARK,
            issued_at: ORIGINAL_ISSUED_AT,
            recorded_at: ORIGINAL_ISSUED_AT + 60,
          }),
        )}
        onRecorded={jest.fn()}
      />,
    );
    fillAdjustmentForm();

    fireEvent.click(
      screen.getByRole("button", {
        name: "adminBillingRecordRefundEvidence",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "adminBillingFinalRefundActionsConfirm",
    );
    expect(recordManualRefund).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByLabelText("adminBillingFinalRefundActionsConfirm"),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "adminBillingRecordRefundEvidence",
      }),
    );
    expect(
      await screen.findByText("adminBillingRefundRecordError"),
    ).toBeInTheDocument();
    expect(recordManualRefund).toHaveBeenCalledTimes(1);
    await Promise.resolve();
    await Promise.resolve();
    expect(recordManualRefund).toHaveBeenCalledTimes(1);
    expect(recordManualRefund).toHaveBeenCalledWith(
      "3".repeat(32),
      expect.objectContaining({ original_document: null }),
    );
  });
});
