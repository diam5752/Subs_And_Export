"use client";

import Link from "next/link";
import { useI18n } from "@/context/I18nContext";

export type CheckoutNoticeKind = "pending" | "success" | "error" | "cancelled";

const ICONS: Readonly<Record<CheckoutNoticeKind, string>> = {
  pending: "…",
  success: "✓",
  error: "!",
  cancelled: "×",
};

interface CheckoutReturnNoticeProps {
  message: string;
  kind: CheckoutNoticeKind;
  isInert: boolean;
  canRetry: boolean;
  contractAvailable: boolean;
  onRetry: () => void;
  onDismiss: () => void;
}

function CheckoutNoticeActions({
  canRetry,
  contractAvailable,
  onRetry,
  onDismiss,
}: Pick<
  CheckoutReturnNoticeProps,
  "canRetry" | "contractAvailable" | "onRetry" | "onDismiss"
>) {
  const { t } = useI18n();

  return (
    <span className="checkout-return-notice-actions">
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="checkout-return-notice-action"
        >
          {t("creditPurchaseRetry")}
        </button>
      )}
      {contractAvailable && (
        <Link href="/account/billing" className="checkout-return-notice-link">
          {t("billingContractDownload")}
        </Link>
      )}
      <button
        type="button"
        onClick={onDismiss}
        className="checkout-return-notice-close"
        aria-label={t("closeLabel")}
      >
        ✕
      </button>
    </span>
  );
}

export function CheckoutReturnNotice({
  message,
  kind,
  isInert,
  canRetry,
  contractAvailable,
  onRetry,
  onDismiss,
}: CheckoutReturnNoticeProps) {
  if (!message) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      aria-hidden={isInert || undefined}
      inert={isInert ? true : undefined}
      data-kind={kind}
      data-testid="checkout-return-notice"
      className="checkout-return-notice"
    >
      <span className="checkout-return-notice-icon" aria-hidden="true">
        {ICONS[kind]}
      </span>
      <span className="checkout-return-notice-message">{message}</span>
      <CheckoutNoticeActions
        canRetry={canRetry}
        contractAvailable={contractAvailable}
        onRetry={onRetry}
        onDismiss={onDismiss}
      />
    </div>
  );
}
