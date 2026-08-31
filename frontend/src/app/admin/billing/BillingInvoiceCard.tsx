"use client";

import type {
  BillingAdminPendingInvoice,
  RecordedAadeDocumentResponse,
} from "@/lib/api";
import {
  BillingInvoiceDetails,
  BillingInvoiceSummary,
  BillingRecordPanel,
} from "./BillingInvoiceCardParts";

type InvoiceCardProps = {
  invoice: BillingAdminPendingInvoice;
  onRecorded: (record: RecordedAadeDocumentResponse) => void;
};

function isIssuedInvoice(invoice: BillingAdminPendingInvoice): boolean {
  return (
    invoice.aade_mark !== null ||
    invoice.document_status === "issued" ||
    invoice.document_status === "cancelled"
  );
}

export function BillingInvoiceCard({ invoice, onRecorded }: InvoiceCardProps) {
  const paymentConfirmedAt = invoice.payment?.confirmed_at ?? null;

  return (
    <article
      className="overflow-hidden rounded-3xl border border-[var(--border)] bg-white shadow-sm"
      data-testid={`billing-admin-invoice-${invoice.invoice_id}`}
    >
      <BillingInvoiceSummary invoice={invoice} />
      <BillingInvoiceDetails
        invoice={invoice}
        paymentConfirmedAt={paymentConfirmedAt}
      />
      <BillingRecordPanel
        invoice={invoice}
        isIssued={isIssuedInvoice(invoice)}
        paymentConfirmedAt={paymentConfirmedAt}
        onRecorded={onRecorded}
      />
    </article>
  );
}
