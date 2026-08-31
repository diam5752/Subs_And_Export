"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { BrandLogo } from "@/components/BrandLogo";
import { Spinner } from "@/components/Spinner";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import {
  ApiError,
  api,
  type BillingAdminPendingInvoice,
  type BillingAdminPendingRefund,
  type BillingAdminPendingWithdrawal,
  type BillingWithdrawalResolutionResponse,
  type RecordedAadeDocumentResponse,
  type RecordedManualRefundAccountingResponse,
} from "@/lib/api";
import { ManualRefundCard } from "./ManualRefundCard";
import { WithdrawalReviewCard } from "./WithdrawalReviewCard";
import { BillingInvoiceCard } from "./BillingInvoiceCard";

function BillingAdminNotice({ notice }: { notice: string }) {
  if (!notice) return null;
  return (
    <p
      role="status"
      className="mt-6 rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm font-semibold text-emerald-950"
    >
      {notice}
    </p>
  );
}

function OptionalSpinner({ show }: { show: boolean }) {
  return show ? <Spinner className="h-4 w-4" /> : null;
}

function addRecordedAdjustment(
  withdrawals: BillingAdminPendingWithdrawal[],
  record: RecordedManualRefundAccountingResponse,
): BillingAdminPendingWithdrawal[] {
  return withdrawals.map((withdrawal) => {
    if (withdrawal.purchase_id !== record.purchase_id) return withdrawal;
    const alreadyPresent = withdrawal.available_adjustments.some(
      (item) => item.adjustment_id === record.adjustment_id,
    );
    if (alreadyPresent) return withdrawal;
    return {
      ...withdrawal,
      available_adjustments: [
        ...withdrawal.available_adjustments,
        {
          adjustment_id: record.adjustment_id,
          stripe_refund_id: record.stripe_refund_id,
          amount_cents: record.amount_cents,
          currency: record.currency,
          aade_document_type: record.aade_document_type,
          aade_series: record.aade_series,
          aade_aa: record.aade_aa,
          aade_mark: record.aade_mark,
          issued_at: record.issued_at,
        },
      ],
    };
  });
}

function BillingAdminState({
  busy,
  signedIn,
  accessDenied,
  loadError,
  empty,
  onRefresh,
  t,
  children,
}: {
  busy: boolean;
  signedIn: boolean;
  accessDenied: boolean;
  loadError: string;
  empty: boolean;
  onRefresh: () => void;
  t: ReturnType<typeof useI18n>["t"];
  children: ReactNode;
}) {
  if (busy) {
    return (
      <div className="grid min-h-64 place-items-center">
        <div className="flex items-center gap-3 text-sm font-semibold text-[var(--muted)]">
          <Spinner className="h-5 w-5" />
          {t("adminBillingLoading")}
        </div>
      </div>
    );
  }
  if (!signedIn) {
    return (
      <div className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-6">
        <p>{t("adminBillingSignIn")}</p>
        <Link
          href="/login"
          className="mt-4 inline-flex min-h-11 items-center font-bold text-[var(--accent)] underline"
        >
          {t("loginSubmit")}
        </Link>
      </div>
    );
  }
  if (accessDenied) {
    return (
      <p
        role="alert"
        className="mt-8 rounded-2xl border border-red-300 bg-red-50 p-6 text-red-900"
      >
        {t("adminBillingForbidden")}
      </p>
    );
  }
  if (loadError) {
    return (
      <div className="mt-8 rounded-2xl border border-red-300 bg-red-50 p-6">
        <p role="alert" className="text-red-900">
          {loadError}
        </p>
        <button
          type="button"
          onClick={onRefresh}
          className="mt-4 min-h-11 rounded-xl border border-red-400 px-4 font-bold text-red-900"
        >
          {t("adminBillingRefresh")}
        </button>
      </div>
    );
  }
  if (empty) {
    return (
      <div className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-6">
        <p>{t("adminBillingEmpty")}</p>
        <button
          type="button"
          onClick={onRefresh}
          className="mt-4 min-h-11 rounded-xl border border-[var(--border-strong)] px-4 font-bold"
        >
          {t("adminBillingRefresh")}
        </button>
      </div>
    );
  }
  return children;
}

export default function BillingAdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const { t } = useI18n();
  const [items, setItems] = useState<BillingAdminPendingInvoice[]>([]);
  const [refunds, setRefunds] = useState<BillingAdminPendingRefund[]>([]);
  const [withdrawals, setWithdrawals] = useState<
    BillingAdminPendingWithdrawal[]
  >([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [refundNextCursor, setRefundNextCursor] = useState<string | null>(null);
  const [withdrawalNextCursor, setWithdrawalNextCursor] = useState<
    string | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingMoreRefunds, setLoadingMoreRefunds] = useState(false);
  const [loadingMoreWithdrawals, setLoadingMoreWithdrawals] = useState(false);
  const [accessDenied, setAccessDenied] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");

  const loadInvoices = useCallback(
    async ({
      after = null,
      append = false,
    }: {
      after?: string | null;
      append?: boolean;
    } = {}) => {
      if (!user) {
        setItems([]);
        setRefunds([]);
        setWithdrawals([]);
        setNextCursor(null);
        setRefundNextCursor(null);
        setWithdrawalNextCursor(null);
        setLoading(false);
        return;
      }
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setAccessDenied(false);
        setLoadError("");
      }
      try {
        const response = await api.listPendingBillingInvoices(
          after ?? undefined,
        );
        setItems((current) => {
          if (!append) {
            return response.items;
          }
          const existing = new Set(current.map((item) => item.invoice_id));
          return [
            ...current,
            ...response.items.filter((item) => !existing.has(item.invoice_id)),
          ];
        });
        setNextCursor(response.next_cursor);
        if (!append) {
          const [refundResponse, withdrawalResponse] = await Promise.all([
            api.listPendingBillingRefunds(),
            api.listPendingBillingWithdrawals(),
          ]);
          setRefunds(refundResponse.items);
          setRefundNextCursor(refundResponse.next_cursor);
          setWithdrawals(withdrawalResponse.items);
          setWithdrawalNextCursor(withdrawalResponse.next_cursor);
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 403) {
          setAccessDenied(true);
        } else {
          setLoadError(t("adminBillingLoadError"));
        }
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [t, user],
  );

  const loadMoreRefunds = useCallback(async () => {
    if (!refundNextCursor) {
      return;
    }
    setLoadingMoreRefunds(true);
    try {
      const response = await api.listPendingBillingRefunds(refundNextCursor);
      setRefunds((current) => {
        const existing = new Set(current.map((item) => item.reversal_id));
        return [
          ...current,
          ...response.items.filter((item) => !existing.has(item.reversal_id)),
        ];
      });
      setRefundNextCursor(response.next_cursor);
    } catch {
      setLoadError(t("adminBillingLoadError"));
    } finally {
      setLoadingMoreRefunds(false);
    }
  }, [refundNextCursor, t]);

  const loadMoreWithdrawals = useCallback(async () => {
    if (!withdrawalNextCursor) {
      return;
    }
    setLoadingMoreWithdrawals(true);
    try {
      const response =
        await api.listPendingBillingWithdrawals(withdrawalNextCursor);
      setWithdrawals((current) => {
        const existing = new Set(current.map((item) => item.withdrawal_id));
        return [
          ...current,
          ...response.items.filter((item) => !existing.has(item.withdrawal_id)),
        ];
      });
      setWithdrawalNextCursor(response.next_cursor);
    } catch {
      setLoadError(t("adminBillingLoadError"));
    } finally {
      setLoadingMoreWithdrawals(false);
    }
  }, [t, withdrawalNextCursor]);

  useEffect(() => {
    if (authLoading) {
      return;
    }
    const timer = window.setTimeout(() => {
      void loadInvoices();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [authLoading, loadInvoices]);

  const handleRecorded = useCallback(
    (record: RecordedAadeDocumentResponse) => {
      setItems((current) =>
        current.filter((item) => item.invoice_id !== record.invoice_id),
      );
      setNotice(t("adminBillingRecorded", { mark: record.aade_mark }));
    },
    [t],
  );

  const handleRefundRecorded = useCallback(
    (record: RecordedManualRefundAccountingResponse) => {
      setRefunds((current) =>
        current.filter((item) => item.reversal_id !== record.reversal_id),
      );
      setWithdrawals((current) => addRecordedAdjustment(current, record));
      setNotice(
        t("adminBillingRefundRecorded", {
          mark: record.aade_mark,
        }),
      );
    },
    [t],
  );

  const handleWithdrawalResolved = useCallback(
    (resolution: BillingWithdrawalResolutionResponse) => {
      setWithdrawals((current) =>
        current.filter(
          (item) => item.withdrawal_id !== resolution.withdrawal_id,
        ),
      );
      setNotice(t("adminBillingWithdrawalResolved"));
    },
    [t],
  );

  const refresh = useCallback(() => {
    setNotice("");
    void loadInvoices();
  }, [loadInvoices]);

  return (
    <div className="min-h-dvh bg-[#f4f4f1] text-[var(--foreground)]">
      <header className="border-b border-[#deded9] bg-[#f7f7f5]">
        <div className="mx-auto flex min-h-[72px] w-full max-w-6xl items-center justify-between gap-4 px-5 sm:px-8">
          <Link href="/" aria-label={t("brandHomeLabel")}>
            <BrandLogo className="block h-auto w-[68px] sm:w-[80px]" />
          </Link>
          <Link
            href="/"
            className="text-sm font-semibold text-[var(--muted)] hover:text-[var(--foreground)]"
          >
            {t("adminBillingBack")}
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 sm:py-16">
        <p className="text-xs font-extrabold tracking-[0.18em] text-[var(--accent)]">
          {t("adminBillingKicker")}
        </p>
        <h1 className="mt-3 text-4xl font-extrabold tracking-[-0.045em] sm:text-6xl">
          {t("adminBillingTitle")}
        </h1>
        <p className="mt-4 max-w-3xl text-base leading-7 text-[var(--muted)]">
          {t("adminBillingDescription")}
        </p>
        <p className="mt-4 max-w-3xl rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm leading-6 text-sky-950">
          {t("adminBillingPrivacyNotice")}
        </p>

        <BillingAdminNotice notice={notice} />

        <BillingAdminState
          busy={authLoading || loading}
          signedIn={Boolean(user)}
          accessDenied={accessDenied}
          loadError={loadError}
          empty={
            items.length === 0 &&
            refunds.length === 0 &&
            withdrawals.length === 0
          }
          onRefresh={refresh}
          t={t}
        >
          <>
            {refunds.length > 0 && (
              <section
                className="mt-10"
                aria-labelledby="refund-accounting-title"
              >
                <h2
                  id="refund-accounting-title"
                  className="text-3xl font-extrabold tracking-[-0.035em]"
                >
                  {t("adminBillingRefundQueueTitle")}
                </h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--muted)]">
                  {t("adminBillingRefundQueueDescription")}
                </p>
                <div className="mt-6 space-y-6">
                  {refunds.map((review) => (
                    <ManualRefundCard
                      key={review.reversal_id}
                      review={review}
                      onRecorded={handleRefundRecorded}
                    />
                  ))}
                </div>
                {refundNextCursor && (
                  <button
                    type="button"
                    disabled={loadingMoreRefunds}
                    onClick={() => void loadMoreRefunds()}
                    className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-xl bg-red-800 px-4 font-bold text-white disabled:opacity-60"
                  >
                    <OptionalSpinner show={loadingMoreRefunds} />
                    {t("adminBillingLoadMoreRefunds")}
                  </button>
                )}
              </section>
            )}

            {withdrawals.length > 0 && (
              <section
                className="mt-10"
                aria-labelledby="withdrawal-review-title"
              >
                <h2
                  id="withdrawal-review-title"
                  className="text-3xl font-extrabold tracking-[-0.035em]"
                >
                  {t("adminBillingWithdrawalQueueTitle")}
                </h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--muted)]">
                  {t("adminBillingWithdrawalQueueDescription")}
                </p>
                <div className="mt-6 space-y-6">
                  {withdrawals.map((review) => (
                    <WithdrawalReviewCard
                      key={review.withdrawal_id}
                      review={review}
                      onResolved={handleWithdrawalResolved}
                    />
                  ))}
                </div>
                {withdrawalNextCursor && (
                  <button
                    type="button"
                    disabled={loadingMoreWithdrawals}
                    onClick={() => void loadMoreWithdrawals()}
                    className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-xl bg-amber-800 px-4 font-bold text-white disabled:opacity-60"
                  >
                    <OptionalSpinner show={loadingMoreWithdrawals} />
                    {t("adminBillingLoadMoreWithdrawals")}
                  </button>
                )}
              </section>
            )}

            {items.length > 0 && (
              <section
                className="mt-10"
                aria-labelledby="original-invoice-title"
              >
                <h2
                  id="original-invoice-title"
                  className="text-3xl font-extrabold tracking-[-0.035em]"
                >
                  {t("adminBillingOriginalQueueTitle")}
                </h2>
                <div className="mt-6 space-y-6">
                  {items.map((invoice) => (
                    <BillingInvoiceCard
                      key={invoice.invoice_id}
                      invoice={invoice}
                      onRecorded={handleRecorded}
                    />
                  ))}
                </div>
              </section>
            )}
            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={refresh}
                className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-4 font-bold"
              >
                {t("adminBillingRefresh")}
              </button>
              {nextCursor && (
                <button
                  type="button"
                  disabled={loadingMore}
                  onClick={() =>
                    void loadInvoices({
                      after: nextCursor,
                      append: true,
                    })
                  }
                  className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[var(--foreground)] px-4 font-bold text-white disabled:opacity-60"
                >
                  <OptionalSpinner show={loadingMore} />
                  {t("adminBillingLoadMoreInvoices")}
                </button>
              )}
            </div>
          </>
        </BillingAdminState>
      </main>
    </div>
  );
}
