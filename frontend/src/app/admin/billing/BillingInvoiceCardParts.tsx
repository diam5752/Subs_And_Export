import { useI18n } from "@/context/I18nContext";
import type {
  BillingAdminPendingInvoice,
  RecordedAadeDocumentResponse,
} from "@/lib/api";
import { ATHENS_TIME_ZONE } from "@/lib/billingAdmin";
import { BillingDocumentForm } from "./BillingDocumentForm";

function formattedMoney(
  amountCents: number | null,
  currency: string | null,
  locale: string,
): string {
  if (amountCents === null || !currency) return "—";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(amountCents / 100);
}

function formattedDateTime(
  epochSeconds: number | null,
  locale: string,
): string {
  if (epochSeconds === null) return "—";
  return new Intl.DateTimeFormat(locale, {
    timeZone: ATHENS_TIME_ZONE,
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(epochSeconds * 1000));
}

function Identifier({ value }: { value: string | null }) {
  return value ? (
    <code className="break-all text-xs font-semibold text-[var(--foreground)]">
      {value}
    </code>
  ) : (
    <span aria-label="missing">—</span>
  );
}

function LabeledValue({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--muted)]">
        {label}
      </dt>
      <dd className="mt-1 break-words text-sm text-[var(--foreground)]">
        {children}
      </dd>
    </div>
  );
}

export function BillingInvoiceSummary({
  invoice,
}: {
  invoice: BillingAdminPendingInvoice;
}) {
  const { locale, t } = useI18n();
  const livemode = invoice.payment?.livemode ?? null;
  const statusLabel =
    invoice.document_status === "manual_review_required"
      ? t("adminBillingManualReviewStatus")
      : t("adminBillingPendingStatus");

  return (
    <div className="border-b border-[var(--border)] bg-[#fafaf8] p-5 sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <InvoiceIdentity
          invoice={invoice}
          livemode={livemode}
          statusLabel={statusLabel}
        />
        <InvoiceAmounts invoice={invoice} locale={locale} />
      </div>
    </div>
  );
}

function InvoiceIdentity({
  invoice,
  livemode,
  statusLabel,
}: {
  invoice: BillingAdminPendingInvoice;
  livemode: boolean | null;
  statusLabel: string;
}) {
  const { t } = useI18n();
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-900">
          {statusLabel}
        </span>
        {livemode !== null && <EnvironmentBadge livemode={livemode} />}
      </div>
      <h2 className="mt-4 text-2xl font-extrabold tracking-[-0.03em]">
        {invoice.service.name ?? "GSUBS Credits"}
      </h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        {invoice.package.key ?? "—"} · {invoice.package.credits ?? "—"}{" "}
        {t("adminBillingCredits")}
      </p>
    </div>
  );
}

function EnvironmentBadge({ livemode }: { livemode: boolean }) {
  const { t } = useI18n();
  return (
    <span
      className={`rounded-full px-3 py-1 text-xs font-bold ${
        livemode ? "bg-red-100 text-red-900" : "bg-sky-100 text-sky-900"
      }`}
    >
      {livemode ? t("adminBillingLiveMode") : t("adminBillingTestMode")}
    </span>
  );
}

function InvoiceAmounts({
  invoice,
  locale,
}: {
  invoice: BillingAdminPendingInvoice;
  locale: string;
}) {
  const { t } = useI18n();
  const currency = invoice.payment?.currency ?? null;
  return (
    <div className="text-right">
      <p className="text-2xl font-extrabold">
        {formattedMoney(invoice.tax.gross_amount_cents, currency, locale)}
      </p>
      <p className="mt-1 text-xs text-[var(--muted)]">
        {t("adminBillingNet")}{" "}
        {formattedMoney(invoice.tax.net_amount_cents, currency, locale)} ·{" "}
        {t("adminBillingVat")} {invoice.tax.vat_rate_percent ?? "—"}%:{" "}
        {formattedMoney(invoice.tax.vat_amount_cents, currency, locale)}
      </p>
    </div>
  );
}

export function BillingInvoiceDetails({
  invoice,
  paymentConfirmedAt,
}: {
  invoice: BillingAdminPendingInvoice;
  paymentConfirmedAt: number | null;
}) {
  return (
    <div className="grid gap-7 p-5 sm:p-7 lg:grid-cols-2">
      <PaymentDetails
        invoice={invoice}
        paymentConfirmedAt={paymentConfirmedAt}
      />
      <CustomerDetails invoice={invoice} />
    </div>
  );
}

function PaymentDetails({
  invoice,
  paymentConfirmedAt,
}: {
  invoice: BillingAdminPendingInvoice;
  paymentConfirmedAt: number | null;
}) {
  const { locale, t } = useI18n();
  return (
    <section aria-labelledby={`payment-${invoice.invoice_id}`}>
      <h3
        id={`payment-${invoice.invoice_id}`}
        className="text-base font-extrabold"
      >
        {t("adminBillingPaymentTitle")}
      </h3>
      <dl className="mt-4 grid gap-4">
        <LabeledValue label={t("adminBillingPurchaseId")}>
          <Identifier value={invoice.purchase_id} />
        </LabeledValue>
        <LabeledValue label={t("adminBillingInvoiceId")}>
          <Identifier value={invoice.invoice_id} />
        </LabeledValue>
        <LabeledValue label={t("adminBillingCheckoutId")}>
          <Identifier value={invoice.payment?.checkout_session_id ?? null} />
        </LabeledValue>
        <LabeledValue label={t("adminBillingPaymentIntentId")}>
          <Identifier value={invoice.payment?.payment_intent_id ?? null} />
        </LabeledValue>
        <LabeledValue label={t("adminBillingPaymentConfirmed")}>
          {formattedDateTime(paymentConfirmedAt, locale)}{" "}
          <span className="text-xs text-[var(--muted)]">
            ({ATHENS_TIME_ZONE})
          </span>
        </LabeledValue>
      </dl>
    </section>
  );
}

type CustomerRecord = NonNullable<BillingAdminPendingInvoice["customer"]>;

function valueOrDash(value: string | null): string {
  return value ?? "—";
}

function customerAddress(customer: CustomerRecord): string {
  return [
    customer.line1,
    customer.line2,
    [customer.postal_code, customer.city].filter(Boolean).join(" "),
    customer.country,
  ]
    .filter(Boolean)
    .join(", ");
}

function customerDetailsView(invoice: BillingAdminPendingInvoice) {
  const customer = invoice.customer;
  const serviceCode = valueOrDash(invoice.service.code);
  const serviceName = valueOrDash(invoice.service.name);
  if (!customer) {
    return {
      serviceCode,
      serviceName,
      name: "—",
      email: "—",
      address: "—",
      missingFields: [] as string[],
    };
  }
  return {
    serviceCode,
    serviceName,
    name: valueOrDash(customer.name),
    email: valueOrDash(customer.email),
    address: customerAddress(customer) || "—",
    missingFields: customer.missing_required_fields ?? [],
  };
}

function CustomerDetails({ invoice }: { invoice: BillingAdminPendingInvoice }) {
  const { t } = useI18n();
  const view = customerDetailsView(invoice);
  return (
    <section aria-labelledby={`customer-${invoice.invoice_id}`}>
      <h3
        id={`customer-${invoice.invoice_id}`}
        className="text-base font-extrabold"
      >
        {t("adminBillingCustomerTitle")}
      </h3>
      <dl className="mt-4 grid gap-4">
        <LabeledValue label={t("adminBillingService")}>
          {view.serviceCode} · {view.serviceName}
        </LabeledValue>
        <LabeledValue label={t("adminBillingCustomerName")}>
          {view.name}
        </LabeledValue>
        <LabeledValue label={t("adminBillingCustomerEmail")}>
          {view.email}
        </LabeledValue>
        <LabeledValue label={t("adminBillingCustomerAddress")}>
          {view.address}
        </LabeledValue>
        {view.missingFields.length > 0 && (
          <LabeledValue label={t("adminBillingMissingFields")}>
            <span className="font-semibold text-amber-800">
              {view.missingFields.join(", ")}
            </span>
          </LabeledValue>
        )}
      </dl>
    </section>
  );
}

export function BillingRecordPanel({
  invoice,
  isIssued,
  paymentConfirmedAt,
  onRecorded,
}: {
  invoice: BillingAdminPendingInvoice;
  isIssued: boolean;
  paymentConfirmedAt: number | null;
  onRecorded: (record: RecordedAadeDocumentResponse) => void;
}) {
  return (
    <div className="border-t border-[var(--border)] bg-[#fcfcfb] p-5 sm:p-7">
      <BillingRecordState
        invoice={invoice}
        isIssued={isIssued}
        paymentConfirmedAt={paymentConfirmedAt}
        onRecorded={onRecorded}
      />
    </div>
  );
}

function BillingRecordState({
  invoice,
  isIssued,
  paymentConfirmedAt,
  onRecorded,
}: {
  invoice: BillingAdminPendingInvoice;
  isIssued: boolean;
  paymentConfirmedAt: number | null;
  onRecorded: (record: RecordedAadeDocumentResponse) => void;
}) {
  const { t } = useI18n();
  if (invoice.requires_reversal_review) {
    return (
      <RecordAlert
        className="border-red-300 bg-red-50 text-red-900"
        message={t("adminBillingReversalWarning")}
      />
    );
  }
  if (isIssued) return <IssuedDocumentReview invoice={invoice} />;
  if (paymentConfirmedAt === null) {
    return (
      <RecordAlert
        className="border-amber-300 bg-amber-50 text-amber-950"
        message={`${t("adminBillingManualReviewStatus")}: ${t("adminBillingBeforePayment")}`}
      />
    );
  }
  return (
    <BillingDocumentForm
      invoiceId={invoice.invoice_id}
      paymentConfirmedAt={paymentConfirmedAt}
      onRecorded={onRecorded}
    />
  );
}

function RecordAlert({
  className,
  message,
}: {
  className: string;
  message: string;
}) {
  return (
    <p
      role="alert"
      className={`rounded-2xl border p-4 text-sm font-semibold leading-6 ${className}`}
    >
      {message}
    </p>
  );
}

function IssuedDocumentReview({
  invoice,
}: {
  invoice: BillingAdminPendingInvoice;
}) {
  const { locale, t } = useI18n();
  return (
    <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4">
      <p className="text-sm font-semibold leading-6 text-amber-950">
        {t("adminBillingIssuedReview")}
      </p>
      <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <LabeledValue label={t("adminBillingDocumentType")}>
          {invoice.aade_document_type ?? "—"}
        </LabeledValue>
        <LabeledValue label={t("adminBillingSeries")}>
          {invoice.aade_series ?? "—"}
        </LabeledValue>
        <LabeledValue label={t("adminBillingAa")}>
          {invoice.aade_aa ?? "—"}
        </LabeledValue>
        <LabeledValue label={t("adminBillingMark")}>
          <Identifier value={invoice.aade_mark} />
        </LabeledValue>
        <LabeledValue label={t("adminBillingIssuedAt")}>
          {formattedDateTime(invoice.issued_at, locale)}
        </LabeledValue>
      </dl>
    </div>
  );
}
