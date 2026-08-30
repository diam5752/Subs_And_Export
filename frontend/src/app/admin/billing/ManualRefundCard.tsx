"use client";

import { useState } from "react";
import {
  type FieldErrors,
  type UseFormRegister,
  useForm,
} from "react-hook-form";
import { Spinner } from "@/components/Spinner";
import { useI18n } from "@/context/I18nContext";
import {
  ApiError,
  api,
  type BillingAdminPendingRefund,
  type RecordedManualRefundAccountingResponse,
} from "@/lib/api";
import {
  AADE_GREEK_B2C_DOCUMENT_TYPE,
  AADE_GREEK_B2C_SERIES,
  ATHENS_TIME_ZONE,
  currentEpochSeconds,
  isCanonicalAadeMark,
  isSupportedAadeSeries,
  parseAthensDateTime,
} from "@/lib/billingAdmin";

type ManualRefundFormValues = {
  originalAa: string;
  originalMark: string;
  originalMarkRepeat: string;
  originalIssuedAt: string;
  adjustmentDocumentType: string;
  adjustmentSeries: string;
  adjustmentAa: string;
  adjustmentMark: string;
  adjustmentMarkRepeat: string;
  adjustmentIssuedAt: string;
  finalManualActionsConfirmed: boolean;
};

type ManualRefundCardProps = {
  review: BillingAdminPendingRefund;
  onRecorded: (record: RecordedManualRefundAccountingResponse) => void;
};

type Translate = ReturnType<typeof useI18n>["t"];
type OriginalInvoice = BillingAdminPendingRefund["original_invoice"];

function hasRecordedOriginalDocument(invoice: OriginalInvoice): boolean {
  return (
    invoice.document_status === "issued" &&
    invoice.aade_document_type !== null &&
    invoice.aade_series !== null &&
    invoice.aade_aa !== null &&
    invoice.aade_mark !== null &&
    invoice.issued_at !== null
  );
}

function formatMoney(
  amountCents: number,
  currency: string,
  locale: string,
): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(amountCents / 100);
}

function formatDateTime(epochSeconds: number, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    timeZone: ATHENS_TIME_ZONE,
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(epochSeconds * 1000));
}

function ManualRefundActions({
  register,
  errors,
  recordError,
  isSubmitting,
  originalAlreadyRecorded,
  paymentConfirmedAt,
  t,
}: {
  register: UseFormRegister<ManualRefundFormValues>;
  errors: FieldErrors<ManualRefundFormValues>;
  recordError: string;
  isSubmitting: boolean;
  originalAlreadyRecorded: boolean;
  paymentConfirmedAt: number | null;
  t: Translate;
}) {
  const recordingBlocked =
    !originalAlreadyRecorded && paymentConfirmedAt === null;
  return (
    <>
      <label className="flex items-start gap-3 rounded-2xl border border-red-300 bg-red-50 p-4 text-sm font-semibold leading-6 text-red-950">
        <input
          type="checkbox"
          className="mt-1 h-5 w-5 shrink-0 accent-red-700"
          {...register("finalManualActionsConfirmed", {
            required: t("adminBillingFinalRefundActionsConfirm"),
          })}
        />
        <span>{t("adminBillingFinalRefundActionsConfirm")}</span>
      </label>
      {errors.finalManualActionsConfirmed && (
        <p role="alert" className="text-sm text-red-700">
          {errors.finalManualActionsConfirmed.message}
        </p>
      )}
      {recordError && (
        <p
          role="alert"
          className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"
        >
          {recordError}
        </p>
      )}
      <button
        type="submit"
        disabled={isSubmitting || recordingBlocked}
        className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-red-800 px-5 font-bold text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSubmitting && <Spinner className="h-4 w-4" />}
        {isSubmitting
          ? t("adminBillingRecording")
          : t("adminBillingRecordRefundEvidence")}
      </button>
    </>
  );
}

export function ManualRefundCard({
  review,
  onRecorded,
}: ManualRefundCardProps) {
  const { locale, t } = useI18n();
  const [recordError, setRecordError] = useState("");
  const invoice = review.original_invoice;
  const originalAlreadyRecorded = hasRecordedOriginalDocument(invoice);
  const paymentConfirmedAt = invoice.payment?.confirmed_at ?? null;
  const {
    formState: { errors, isSubmitting },
    getValues,
    handleSubmit,
    register,
  } = useForm<ManualRefundFormValues>({
    defaultValues: {
      originalAa: "",
      originalMark: "",
      originalMarkRepeat: "",
      originalIssuedAt: "",
      adjustmentDocumentType: "",
      adjustmentSeries: "",
      adjustmentAa: "",
      adjustmentMark: "",
      adjustmentMarkRepeat: "",
      adjustmentIssuedAt: "",
      finalManualActionsConfirmed: false,
    },
  });

  const submitAccounting = handleSubmit(async (values) => {
    const adjustmentIssuedAt = parseAthensDateTime(values.adjustmentIssuedAt);
    const originalIssuedAt = originalAlreadyRecorded
      ? null
      : parseAthensDateTime(values.originalIssuedAt);
    if (
      adjustmentIssuedAt === null ||
      (!originalAlreadyRecorded && originalIssuedAt === null)
    ) {
      return;
    }
    setRecordError("");
    try {
      const record = await api.recordManualRefundAccounting(
        review.reversal_id,
        {
          original_document: originalAlreadyRecorded
            ? null
            : {
                document_type: AADE_GREEK_B2C_DOCUMENT_TYPE,
                series: AADE_GREEK_B2C_SERIES,
                aa: values.originalAa,
                mark: values.originalMark,
                issued_at: originalIssuedAt as number,
              },
          adjustment_document: {
            document_type: values.adjustmentDocumentType.trim(),
            series: values.adjustmentSeries.trim(),
            aa: values.adjustmentAa,
            mark: values.adjustmentMark,
            issued_at: adjustmentIssuedAt,
          },
          final_manual_actions_confirmed: true,
        },
      );
      onRecorded(record);
    } catch (error) {
      // Permanent evidence writes are never retried automatically.
      setRecordError(
        error instanceof ApiError && error.status === 403
          ? t("adminBillingRecentSignInRequired")
          : t("adminBillingRefundRecordError"),
      );
    }
  });

  return (
    <article
      className="overflow-hidden rounded-3xl border border-red-200 bg-white shadow-sm"
      data-testid={`billing-admin-refund-${review.reversal_id}`}
    >
      <div className="border-b border-red-200 bg-red-50 p-5 sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <span className="rounded-full bg-red-700 px-3 py-1 text-xs font-bold text-white">
              {t("adminBillingRefundCompletedBadge")}
            </span>
            <h3 className="mt-4 text-2xl font-extrabold">
              {t("adminBillingRefundTitle")}
            </h3>
            <p className="mt-2 break-all font-mono text-xs">
              {review.stripe_refund_id}
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-extrabold">
              {formatMoney(review.amount_cents, review.currency, locale)}
            </p>
            <p className="mt-1 text-xs text-red-900">
              {formatDateTime(review.stripe_refund_created_at, locale)}
              {" · "}
              {ATHENS_TIME_ZONE}
            </p>
          </div>
        </div>
        <p className="mt-4 max-w-4xl text-sm font-semibold leading-6 text-red-950">
          {t("adminBillingRefundNoAutomation")}
        </p>
      </div>

      <form
        className="space-y-7 p-5 sm:p-7"
        onSubmit={(event) => void submitAccounting(event)}
        noValidate
      >
        <section className="space-y-4">
          <div>
            <h4 className="text-lg font-extrabold">
              {t("adminBillingOriginalDocumentTitle")}
            </h4>
            <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
              {originalAlreadyRecorded
                ? t("adminBillingOriginalAlreadyRecorded")
                : t("adminBillingOriginalRequiredForRefund")}
            </p>
          </div>
          {originalAlreadyRecorded ? (
            <dl className="grid gap-3 rounded-2xl border border-[var(--border)] bg-[#fafaf8] p-4 sm:grid-cols-5">
              <div>
                <dt className="text-xs font-bold text-[var(--muted)]">
                  {t("adminBillingDocumentType")}
                </dt>
                <dd>{invoice.aade_document_type}</dd>
              </div>
              <div>
                <dt className="text-xs font-bold text-[var(--muted)]">
                  {t("adminBillingSeries")}
                </dt>
                <dd>{invoice.aade_series}</dd>
              </div>
              <div>
                <dt className="text-xs font-bold text-[var(--muted)]">
                  {t("adminBillingAa")}
                </dt>
                <dd>{invoice.aade_aa}</dd>
              </div>
              <div>
                <dt className="text-xs font-bold text-[var(--muted)]">
                  {t("adminBillingMark")}
                </dt>
                <dd className="break-all font-mono text-xs">
                  {invoice.aade_mark}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-bold text-[var(--muted)]">
                  {t("adminBillingIssuedAt")}
                </dt>
                <dd>{formatDateTime(invoice.issued_at as number, locale)}</dd>
              </div>
            </dl>
          ) : paymentConfirmedAt === null ? (
            <p
              role="alert"
              className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm font-semibold text-red-900"
            >
              {t("adminBillingBeforePayment")}
            </p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <label className="grid gap-2 text-sm font-semibold">
                {t("adminBillingDocumentType")}
                <input
                  value={AADE_GREEK_B2C_DOCUMENT_TYPE}
                  readOnly
                  aria-readonly="true"
                  className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-[#f4f4f1] px-3"
                />
              </label>
              <label className="grid gap-2 text-sm font-semibold">
                {t("adminBillingSeries")}
                <input
                  value={AADE_GREEK_B2C_SERIES}
                  readOnly
                  aria-readonly="true"
                  className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-[#f4f4f1] px-3"
                />
              </label>
              <label className="grid gap-2 text-sm font-semibold">
                {t("adminBillingAa")}
                <input
                  autoComplete="off"
                  inputMode="numeric"
                  className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3"
                  {...register("originalAa", {
                    required: t("adminBillingInvalidAa"),
                    maxLength: 64,
                    pattern: {
                      value: /^[0-9]+$/,
                      message: t("adminBillingInvalidAa"),
                    },
                  })}
                />
                {errors.originalAa && (
                  <span role="alert" className="text-xs text-red-700">
                    {t("adminBillingInvalidAa")}
                  </span>
                )}
              </label>
              <label className="grid gap-2 text-sm font-semibold">
                {t("adminBillingMark")}
                <input
                  autoComplete="off"
                  inputMode="numeric"
                  className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3 font-mono"
                  {...register("originalMark", {
                    required: t("adminBillingInvalidMark"),
                    validate: (value) =>
                      isCanonicalAadeMark(value) ||
                      t("adminBillingInvalidMark"),
                  })}
                />
                {errors.originalMark && (
                  <span role="alert" className="text-xs text-red-700">
                    {errors.originalMark.message}
                  </span>
                )}
              </label>
              <label className="grid gap-2 text-sm font-semibold">
                {t("adminBillingMarkRepeat")}
                <input
                  autoComplete="off"
                  inputMode="numeric"
                  className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3 font-mono"
                  {...register("originalMarkRepeat", {
                    required: t("adminBillingMarkMismatch"),
                    validate: (value) =>
                      value === getValues("originalMark") ||
                      t("adminBillingMarkMismatch"),
                  })}
                />
                {errors.originalMarkRepeat && (
                  <span role="alert" className="text-xs text-red-700">
                    {errors.originalMarkRepeat.message}
                  </span>
                )}
              </label>
              <label className="grid gap-2 text-sm font-semibold">
                {t("adminBillingIssuedAt")}
                <input
                  type="datetime-local"
                  step="60"
                  className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3"
                  {...register("originalIssuedAt", {
                    required: t("adminBillingInvalidIssuedAt"),
                    validate: (value) => {
                      const issuedAt = parseAthensDateTime(value);
                      if (issuedAt === null) {
                        return t("adminBillingInvalidIssuedAt");
                      }
                      if (issuedAt > currentEpochSeconds()) {
                        return t("adminBillingFutureIssuedAt");
                      }
                      if (
                        paymentConfirmedAt !== null &&
                        issuedAt < paymentConfirmedAt
                      ) {
                        return t("adminBillingBeforePayment");
                      }
                      return true;
                    },
                  })}
                />
                {errors.originalIssuedAt && (
                  <span role="alert" className="text-xs text-red-700">
                    {errors.originalIssuedAt.message}
                  </span>
                )}
              </label>
            </div>
          )}
        </section>

        <section className="space-y-4 border-t border-[var(--border)] pt-7">
          <div>
            <h4 className="text-lg font-extrabold">
              {t("adminBillingAdjustmentDocumentTitle")}
            </h4>
            <p className="mt-1 text-sm font-semibold leading-6 text-amber-900">
              {t("adminBillingAdjustmentNoDefaults")}
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <label className="grid gap-2 text-sm font-semibold">
              {t("adminBillingDocumentType")}
              <input
                autoComplete="off"
                inputMode="decimal"
                className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3"
                {...register("adjustmentDocumentType", {
                  required: t("adminBillingInvalidAdjustmentType"),
                  pattern: {
                    value: /^[0-9]{1,2}(?:\.[0-9]{1,2})?$/,
                    message: t("adminBillingInvalidAdjustmentType"),
                  },
                })}
              />
              {errors.adjustmentDocumentType && (
                <span role="alert" className="text-xs text-red-700">
                  {errors.adjustmentDocumentType.message}
                </span>
              )}
            </label>
            <label className="grid gap-2 text-sm font-semibold">
              {t("adminBillingSeries")}
              <input
                autoComplete="off"
                maxLength={32}
                className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3"
                {...register("adjustmentSeries", {
                  required: t("adminBillingInvalidAdjustmentSeries"),
                  validate: (value) =>
                    isSupportedAadeSeries(value) ||
                    t("adminBillingInvalidAdjustmentSeries"),
                })}
              />
              {errors.adjustmentSeries && (
                <span role="alert" className="text-xs text-red-700">
                  {errors.adjustmentSeries.message}
                </span>
              )}
            </label>
            <label className="grid gap-2 text-sm font-semibold">
              {t("adminBillingAa")}
              <input
                autoComplete="off"
                inputMode="numeric"
                className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3"
                {...register("adjustmentAa", {
                  required: t("adminBillingInvalidAa"),
                  maxLength: 64,
                  pattern: {
                    value: /^[0-9]+$/,
                    message: t("adminBillingInvalidAa"),
                  },
                })}
              />
              {errors.adjustmentAa && (
                <span role="alert" className="text-xs text-red-700">
                  {t("adminBillingInvalidAa")}
                </span>
              )}
            </label>
            <label className="grid gap-2 text-sm font-semibold">
              {t("adminBillingMark")}
              <input
                autoComplete="off"
                inputMode="numeric"
                className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3 font-mono"
                {...register("adjustmentMark", {
                  required: t("adminBillingInvalidMark"),
                  validate: (value) => {
                    if (!isCanonicalAadeMark(value)) {
                      return t("adminBillingInvalidMark");
                    }
                    const originalMark = originalAlreadyRecorded
                      ? invoice.aade_mark
                      : getValues("originalMark");
                    return (
                      value !== originalMark ||
                      t("adminBillingAdjustmentIdentityConflict")
                    );
                  },
                })}
              />
              {errors.adjustmentMark && (
                <span role="alert" className="text-xs text-red-700">
                  {errors.adjustmentMark.message}
                </span>
              )}
            </label>
            <label className="grid gap-2 text-sm font-semibold">
              {t("adminBillingMarkRepeat")}
              <input
                autoComplete="off"
                inputMode="numeric"
                className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3 font-mono"
                {...register("adjustmentMarkRepeat", {
                  required: t("adminBillingMarkMismatch"),
                  validate: (value) =>
                    value === getValues("adjustmentMark") ||
                    t("adminBillingMarkMismatch"),
                })}
              />
              {errors.adjustmentMarkRepeat && (
                <span role="alert" className="text-xs text-red-700">
                  {errors.adjustmentMarkRepeat.message}
                </span>
              )}
            </label>
            <label className="grid gap-2 text-sm font-semibold">
              {t("adminBillingIssuedAt")}
              <input
                type="datetime-local"
                step="60"
                className="min-h-11 rounded-xl border border-[var(--border-strong)] px-3"
                {...register("adjustmentIssuedAt", {
                  required: t("adminBillingInvalidIssuedAt"),
                  validate: (value) => {
                    const issuedAt = parseAthensDateTime(value);
                    if (issuedAt === null) {
                      return t("adminBillingInvalidIssuedAt");
                    }
                    if (issuedAt > currentEpochSeconds()) {
                      return t("adminBillingFutureIssuedAt");
                    }
                    if (issuedAt < review.stripe_refund_created_at) {
                      return t("adminBillingAdjustmentBeforeRefund");
                    }
                    return true;
                  },
                })}
              />
              {errors.adjustmentIssuedAt && (
                <span role="alert" className="text-xs text-red-700">
                  {errors.adjustmentIssuedAt.message}
                </span>
              )}
            </label>
          </div>
        </section>

        <ManualRefundActions
          register={register}
          errors={errors}
          recordError={recordError}
          isSubmitting={isSubmitting}
          originalAlreadyRecorded={originalAlreadyRecorded}
          paymentConfirmedAt={paymentConfirmedAt}
          t={t}
        />
      </form>
    </article>
  );
}
