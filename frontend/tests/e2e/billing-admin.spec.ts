import { expect, test, type Page, type Route } from "@playwright/test";
import el from "@/i18n/el.json";
import { mockApi } from "./mocks";

const pendingInvoiceId = "1".repeat(32);
const reversalInvoiceId = "2".repeat(32);
const refundReversalId = "6".repeat(32);
const withdrawalId = "7".repeat(32);
const adjustmentId = "8".repeat(32);
const stripeRefundId = "re_completed_admin_e2e";

const pendingInvoice = {
  invoice_id: pendingInvoiceId,
  purchase_id: "3".repeat(32),
  document_status: "pending_manual_issue",
  purchase_status: "paid",
  provider: "stripe",
  document_kind: "receipt",
  refunded_amount_cents: 0,
  reversed_amount_cents: 0,
  reversed_credits: 0,
  dispute_active: false,
  requires_reversal_review: false,
  aade_document_type: null,
  aade_series: null,
  aade_aa: null,
  aade_mark: null,
  issued_at: null,
  created_at: 1_700_000_100,
  financial_retention_until: 2_100_000_000,
  package: {
    key: "starter",
    credits: 100,
  },
  payment: {
    checkout_session_id: "cs_test_admin_e2e",
    payment_intent_id: "pi_test_admin_e2e",
    confirmed_at: 1_700_000_000,
    livemode: false,
    amount_paid_cents: 100,
    currency: "eur",
    payment_status: "paid",
  },
  customer: {
    name: "Ελένη Παπαδοπούλου",
    email: "eleni@example.com",
    country: "GR",
    city: "Αθήνα",
    postal_code: "10557",
    line1: "Σύνταγμα 1",
    line2: null,
    state: "Αττική",
    status: "complete",
    missing_required_fields: [],
  },
  tax: {
    gross_amount_cents: 100,
    net_amount_cents: 81,
    vat_amount_cents: 19,
    vat_rate_percent: 24,
  },
  service: {
    code: "gsubs_credits",
    name: "GSUBS Credits",
  },
};

const reversalInvoice = {
  ...pendingInvoice,
  invoice_id: reversalInvoiceId,
  purchase_id: "4".repeat(32),
  refunded_amount_cents: 100,
  reversed_amount_cents: 100,
  reversed_credits: 100,
  requires_reversal_review: true,
  document_status: "issued",
  aade_document_type: "11.2",
  aade_series: "0",
  aade_aa: "7",
  aade_mark: "123456789012345678",
  issued_at: 1_705_314_600,
};

const pendingRefund = {
  reversal_id: refundReversalId,
  stripe_refund_id: stripeRefundId,
  stripe_refund_status: "succeeded",
  stripe_refund_created_at: 1_705_318_200,
  amount_cents: 100,
  currency: "eur",
  linked_withdrawal_id: withdrawalId,
  original_invoice: reversalInvoice,
};

const pendingWithdrawal = {
  withdrawal_id: withdrawalId,
  purchase_id: reversalInvoice.purchase_id,
  locale: "el",
  submitted_at: 1_705_317_000,
  contract_concluded_at: 1_705_314_600,
  confirmed_name: "Ελένη Παπαδοπούλου",
  confirmation_email: "eleni@example.com",
  available_adjustments: [],
};

const recordedAdjustment = {
  adjustment_id: adjustmentId,
  purchase_id: reversalInvoice.purchase_id,
  reversal_id: refundReversalId,
  stripe_refund_id: stripeRefundId,
  amount_cents: 100,
  currency: "eur",
  aade_document_type: "11.4",
  aade_series: "ΠΙΣ",
  aade_aa: "8",
  aade_mark: "223456789012345678",
  issued_at: 1_705_321_800,
  recorded_at: 1_705_321_900,
  financial_retention_until: 2_100_000_000,
  original_invoice_status: "issued",
  original_invoice_mark: reversalInvoice.aade_mark,
};

const corsHeaders = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
};

async function fulfillJson(
  route: Route,
  body: unknown,
  status = 200,
): Promise<void> {
  if (route.request().method() === "OPTIONS") {
    const origin = route.request().headers().origin ?? "http://localhost:3000";
    await route.fulfill({
      status: 200,
      headers: {
        ...corsHeaders,
        "access-control-allow-origin": origin,
        "access-control-allow-credentials": "true",
      },
    });
    return;
  }
  await route.fulfill({
    status,
    headers: corsHeaders,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockBillingAdmin(
  page: Page,
  recordedPayloads: unknown[],
): Promise<void> {
  await page.route("**/billing/admin/invoices/pending*", async (route) => {
    await fulfillJson(route, {
      items: [pendingInvoice, reversalInvoice],
      count: 2,
      next_cursor: null,
    });
  });
  await page.route("**/billing/admin/refunds/pending*", async (route) => {
    await fulfillJson(route, {
      items: [],
      count: 0,
      next_cursor: null,
    });
  });
  await page.route("**/billing/admin/withdrawals/pending*", async (route) => {
    await fulfillJson(route, {
      items: [],
      count: 0,
      next_cursor: null,
    });
  });
  await page.route(
    `**/billing/admin/invoices/${pendingInvoiceId}/record-issued`,
    async (route) => {
      if (route.request().method() === "POST") {
        recordedPayloads.push(route.request().postDataJSON());
      }
      await fulfillJson(route, {
        invoice_id: pendingInvoiceId,
        purchase_id: pendingInvoice.purchase_id,
        document_status: "issued",
        aade_document_type: "11.2",
        aade_series: "0",
        aade_aa: "1",
        aade_mark: "987654321012345678",
        issued_at: 1_705_314_600,
        financial_retention_until: 2_100_000_000,
        recorded_at: 1_705_314_700,
      });
    },
  );
}

async function mockManualRefundReview(
  page: Page,
  accountingPayloads: unknown[],
  resolutionPayloads: unknown[],
): Promise<void> {
  await page.route("**/billing/admin/invoices/pending*", async (route) => {
    await fulfillJson(route, {
      items: [],
      count: 0,
      next_cursor: null,
    });
  });
  await page.route("**/billing/admin/refunds/pending*", async (route) => {
    await fulfillJson(route, {
      items: [pendingRefund],
      count: 1,
      next_cursor: null,
    });
  });
  await page.route("**/billing/admin/withdrawals/pending*", async (route) => {
    await fulfillJson(route, {
      items: [pendingWithdrawal],
      count: 1,
      next_cursor: null,
    });
  });
  await page.route(
    `**/billing/admin/refunds/${refundReversalId}/record-aade-adjustment`,
    async (route) => {
      if (route.request().method() === "POST") {
        accountingPayloads.push(route.request().postDataJSON());
      }
      await fulfillJson(route, recordedAdjustment);
    },
  );
  await page.route(
    `**/billing/admin/withdrawals/${withdrawalId}/resolve`,
    async (route) => {
      if (route.request().method() === "POST") {
        resolutionPayloads.push(route.request().postDataJSON());
      }
      await fulfillJson(route, {
        resolution_id: "9".repeat(32),
        withdrawal_id: withdrawalId,
        purchase_id: reversalInvoice.purchase_id,
        decision: "accepted_refunded",
        reason_code: "statutory_right_accepted",
        adjustment_id: adjustmentId,
        resolved_at: 1_705_322_000,
        resolution_sha256: "a".repeat(64),
        resolution_url:
          `/billing/purchases/${reversalInvoice.purchase_id}` +
          "/withdrawal-resolution",
      });
    },
  );
}

test("admin records only a confirmed, already-issued AADE document", async ({
  page,
}) => {
  const recordedPayloads: unknown[] = [];
  await mockApi(page);
  await mockBillingAdmin(page, recordedPayloads);

  await page.goto("/admin/billing");

  const pendingCard = page.getByTestId(
    `billing-admin-invoice-${pendingInvoiceId}`,
  );
  const reversalCard = page.getByTestId(
    `billing-admin-invoice-${reversalInvoiceId}`,
  );
  await expect(pendingCard).toBeVisible();
  await expect(pendingCard).toContainText("cs_test_admin_e2e");
  await expect(pendingCard).toContainText("Ελένη Παπαδοπούλου");
  await expect(reversalCard).toContainText(el.adminBillingReversalWarning);
  await expect(
    reversalCard.getByRole("button", { name: el.adminBillingRecord }),
  ).toHaveCount(0);

  await expect(
    pendingCard.getByLabel(el.adminBillingDocumentType, { exact: true }),
  ).toHaveValue("11.2");
  await expect(
    pendingCard.getByLabel(el.adminBillingDocumentType, { exact: true }),
  ).toHaveAttribute("readonly", "");
  await expect(
    pendingCard.getByLabel(el.adminBillingSeries, { exact: true }),
  ).toHaveValue("0");
  await expect(
    pendingCard.getByLabel(el.adminBillingSeries, { exact: true }),
  ).toHaveAttribute("readonly", "");
  await pendingCard.getByLabel(el.adminBillingAa, { exact: true }).fill("1");
  await pendingCard
    .getByLabel(el.adminBillingMark, { exact: true })
    .fill("987654321012345678");
  await pendingCard
    .getByLabel(el.adminBillingMarkRepeat, { exact: true })
    .fill("987654321012345678");
  await pendingCard.locator('input[name="issuedAt"]').fill("2024-01-15T12:30");
  await pendingCard
    .getByLabel(el.adminBillingFinalDocumentConfirm, { exact: true })
    .check();
  await pendingCard
    .getByRole("button", {
      name: el.adminBillingRecord,
    })
    .click();

  await expect
    .poll(() => recordedPayloads)
    .toEqual([
      {
        document_type: "11.2",
        series: "0",
        aa: "1",
        mark: "987654321012345678",
        issued_at: 1_705_314_600,
      },
    ]);
  await expect(pendingCard).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText("987654321012345678");
  await expect(reversalCard).toBeVisible();
});

test("admin links a completed refund and AADE correction before accepting a withdrawal", async ({
  page,
}) => {
  const accountingPayloads: unknown[] = [];
  const resolutionPayloads: unknown[] = [];
  await mockApi(page);
  await mockManualRefundReview(page, accountingPayloads, resolutionPayloads);

  await page.goto("/admin/billing");

  const refundCard = page.getByTestId(
    `billing-admin-refund-${refundReversalId}`,
  );
  const withdrawalCard = page.getByTestId(
    `billing-admin-withdrawal-${withdrawalId}`,
  );
  await expect(refundCard).toBeVisible();
  await expect(refundCard).toContainText(stripeRefundId);
  await expect(withdrawalCard).toBeVisible();
  await expect(
    withdrawalCard.getByRole("radio", {
      name: new RegExp(el.adminBillingWithdrawalAccept),
    }),
  ).toBeDisabled();

  const adjustmentType = refundCard.locator(
    'input[name="adjustmentDocumentType"]',
  );
  const adjustmentSeries = refundCard.locator('input[name="adjustmentSeries"]');
  const adjustmentAa = refundCard.locator('input[name="adjustmentAa"]');
  const adjustmentMark = refundCard.locator('input[name="adjustmentMark"]');
  const adjustmentMarkRepeat = refundCard.locator(
    'input[name="adjustmentMarkRepeat"]',
  );
  const adjustmentIssuedAt = refundCard.locator(
    'input[name="adjustmentIssuedAt"]',
  );

  await expect(adjustmentType).toHaveValue("");
  await expect(adjustmentSeries).toHaveValue("");
  await expect(adjustmentAa).toHaveValue("");
  await expect(adjustmentMark).toHaveValue("");
  await expect(adjustmentIssuedAt).toHaveValue("");

  await adjustmentType.fill("11.4");
  await adjustmentSeries.fill("ΠΙΣ");
  await adjustmentAa.fill("8");
  await adjustmentMark.fill("223456789012345678");
  await adjustmentMarkRepeat.fill("223456789012345678");
  await adjustmentIssuedAt.fill("2024-01-15T14:30");
  await refundCard
    .getByLabel(el.adminBillingFinalRefundActionsConfirm, { exact: true })
    .check();
  await refundCard
    .getByRole("button", {
      name: el.adminBillingRecordRefundEvidence,
    })
    .click();

  await expect
    .poll(() => accountingPayloads)
    .toEqual([
      {
        original_document: null,
        adjustment_document: {
          document_type: "11.4",
          series: "ΠΙΣ",
          aa: "8",
          mark: "223456789012345678",
          issued_at: 1_705_321_800,
        },
        final_manual_actions_confirmed: true,
      },
    ]);
  await expect(refundCard).toHaveCount(0);

  const accept = withdrawalCard.getByRole("radio", {
    name: new RegExp(el.adminBillingWithdrawalAccept),
  });
  await expect(accept).toBeEnabled();
  await accept.check();
  await withdrawalCard
    .locator('select[name="adjustmentId"]')
    .selectOption(adjustmentId);
  const explanation =
    "Το refund και το διορθωτικό ολοκληρώθηκαν και ελέγχθηκαν χειροκίνητα.";
  await withdrawalCard
    .getByLabel(el.adminBillingWithdrawalCustomerExplanation, { exact: true })
    .fill(explanation);
  await withdrawalCard
    .getByLabel(el.adminBillingFinalWithdrawalReviewConfirm, { exact: true })
    .check();
  await withdrawalCard
    .getByRole("button", {
      name: el.adminBillingResolveWithdrawal,
    })
    .click();

  await expect
    .poll(() => resolutionPayloads)
    .toEqual([
      {
        decision: "accepted_refunded",
        adjustment_id: adjustmentId,
        customer_explanation: explanation,
        final_manual_review_confirmed: true,
      },
    ]);
  await expect(withdrawalCard).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText(
    el.adminBillingWithdrawalResolved,
  );
});
