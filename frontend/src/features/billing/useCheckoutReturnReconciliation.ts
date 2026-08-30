"use client";

import { useCallback, useEffect, useState } from "react";
import type { CheckoutNoticeKind } from "@/components/CheckoutReturnNotice";
import type { MessageKey } from "@/context/i18nMessages";
import {
  api,
  type CreditCheckoutStatusResponse,
  type PointsBalanceResponse,
} from "@/lib/api";

const RECONCILIATION_DELAYS_MS = [
  0, 1_000, 2_000, 4_000, 8_000, 15_000,
] as const;
const NONTERMINAL_STATUSES = new Set([
  "creating",
  "checkout_created",
  "awaiting_payment",
]);
const EMPTY_NOTICE: CheckoutNoticeState = { message: "", kind: "pending" };

type Translate = (
  key: MessageKey,
  params?: Record<string, string | number>,
) => string;
type NoticeSetter = (notice: CheckoutNoticeState) => void;

interface CheckoutNoticeState {
  message: string;
  kind: CheckoutNoticeKind;
}

interface TerminalNotice {
  kind: "success" | "error";
  message: string;
  contractAvailable: boolean;
}

interface ReconciliationControl {
  active: boolean;
  retryTimeout: number | null;
  releaseRetryDelay: (() => void) | null;
}

interface ReconciliationContext {
  sessionId: string;
  control: ReconciliationControl;
  t: Translate;
  setWallet: (wallet: PointsBalanceResponse) => void;
  setNotice: NoticeSetter;
  setContractAvailable: (available: boolean) => void;
  setCanRetry: (canRetry: boolean) => void;
}

interface CheckoutReturnContext extends Omit<
  ReconciliationContext,
  "sessionId" | "control"
> {
  userId: string | null;
  setNoticeOwnerId: (ownerId: string | null) => void;
}

function classifyCheckoutStatus(status: string): string {
  if (status === "paid" || status === "partially_refunded") return "success";
  if (["failed", "expired", "reversed", "disputed"].includes(status))
    return status;
  if (NONTERMINAL_STATUSES.has(status)) return "pending";
  return "pending";
}

function terminalNotice(
  status: CreditCheckoutStatusResponse,
  t: Translate,
): TerminalNotice | null {
  const state = classifyCheckoutStatus(status.status);
  if (state === "success") {
    return {
      kind: "success",
      message: t("creditPurchaseSuccess", {
        count: status.credits,
        balance: status.wallet.balance,
      }),
      contractAvailable: true,
    };
  }
  if (state === "failed")
    return {
      kind: "error",
      message: t("creditPurchaseFailed"),
      contractAvailable: false,
    };
  if (state === "expired")
    return {
      kind: "error",
      message: t("creditPurchaseExpired"),
      contractAvailable: false,
    };
  if (state === "reversed")
    return {
      kind: "error",
      message: t("creditPurchaseReversed"),
      contractAvailable: false,
    };
  if (state === "disputed")
    return {
      kind: "error",
      message: t("creditPurchaseDisputed"),
      contractAvailable: false,
    };
  return null;
}

function clearCheckoutReturnParams(): void {
  const cleaned = new URL(window.location.href);
  cleaned.searchParams.delete("checkout");
  cleaned.searchParams.delete("session_id");
  window.history.replaceState(
    {},
    "",
    `${cleaned.pathname}${cleaned.search}${cleaned.hash}`,
  );
}

function waitForDelay(
  delayMs: number,
  control: ReconciliationControl,
): Promise<void> {
  if (delayMs === 0) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const release = () => {
      if (control.releaseRetryDelay !== release) return;
      control.releaseRetryDelay = null;
      control.retryTimeout = null;
      resolve();
    };
    control.releaseRetryDelay = release;
    control.retryTimeout = window.setTimeout(release, delayMs);
  });
}

function stopReconciliation(control: ReconciliationControl): void {
  control.active = false;
  if (control.retryTimeout !== null) window.clearTimeout(control.retryTimeout);
  control.retryTimeout = null;
  control.releaseRetryDelay?.();
  control.releaseRetryDelay = null;
}

async function reconcileCheckoutAttempt(
  context: ReconciliationContext,
): Promise<boolean> {
  const { control, sessionId, t } = context;
  try {
    const status = await api.getCreditCheckoutStatus(sessionId);
    if (!control.active) return true;
    context.setWallet(status.wallet);
    const notice = terminalNotice(status, t);
    if (notice) {
      context.setNotice({ message: notice.message, kind: notice.kind });
      context.setContractAvailable(notice.contractAvailable);
      clearCheckoutReturnParams();
      return true;
    }
    context.setNotice({
      message: t("creditPurchasePending"),
      kind: "pending",
    });
    return false;
  } catch (error) {
    if (!control.active) return true;
    context.setNotice({
      message:
        error instanceof Error ? error.message : t("creditPurchaseStatusError"),
      kind: "error",
    });
    context.setCanRetry(true);
    return true;
  }
}

async function reconcileCheckout(
  context: ReconciliationContext,
): Promise<void> {
  const { control, t } = context;
  context.setCanRetry(false);
  context.setContractAvailable(false);
  context.setNotice({ message: t("creditPurchasePending"), kind: "pending" });

  for (const delayMs of RECONCILIATION_DELAYS_MS) {
    await waitForDelay(delayMs, control);
    if (!control.active) return;
    if (await reconcileCheckoutAttempt(context)) return;
  }
  if (!control.active) return;
  context.setNotice({
    message: t("creditPurchasePendingRetry"),
    kind: "pending",
  });
  context.setCanRetry(true);
}

function showCancelledNotice(
  control: ReconciliationControl,
  context: CheckoutReturnContext,
): void {
  clearCheckoutReturnParams();
  queueMicrotask(() => {
    if (control.active) {
      context.setNotice({
        message: context.t("creditPurchaseCancelled"),
        kind: "cancelled",
      });
    }
  });
}

function startCheckoutReturnReconciliation(
  context: CheckoutReturnContext,
): (() => void) | undefined {
  context.setNotice(EMPTY_NOTICE);
  context.setContractAvailable(false);
  context.setCanRetry(false);
  context.setNoticeOwnerId(context.userId);
  if (!context.userId || typeof window === "undefined") return undefined;

  const control: ReconciliationControl = {
    active: true,
    retryTimeout: null,
    releaseRetryDelay: null,
  };
  const params = new URLSearchParams(window.location.search);
  const checkoutState = params.get("checkout");
  const sessionId = params.get("session_id");
  if (checkoutState === "cancelled") {
    showCancelledNotice(control, context);
  }
  if (checkoutState === "success" && sessionId) {
    void reconcileCheckout({ ...context, sessionId, control });
  }
  return () => stopReconciliation(control);
}

export function useCheckoutReturnReconciliation({
  userId,
  setWallet,
  t,
}: {
  userId: string | null;
  setWallet: (wallet: PointsBalanceResponse) => void;
  t: Translate;
}) {
  const [notice, setNotice] = useState<CheckoutNoticeState>(EMPTY_NOTICE);
  const [noticeOwnerId, setNoticeOwnerId] = useState<string | null>(null);
  const [contractAvailable, setContractAvailable] = useState(false);
  const [canRetry, setCanRetry] = useState(false);
  const [retryRequest, setRetryRequest] = useState(0);

  useEffect(
    () =>
      startCheckoutReturnReconciliation({
        userId,
        t,
        setWallet,
        setNotice,
        setNoticeOwnerId,
        setContractAvailable,
        setCanRetry,
      }),
    [retryRequest, setWallet, t, userId],
  );

  const retry = useCallback(
    () => setRetryRequest((request) => request + 1),
    [],
  );
  const dismiss = useCallback(() => {
    setNotice((current) => ({ ...current, message: "" }));
  }, []);

  const belongsToCurrentUser = Boolean(userId && noticeOwnerId === userId);
  return {
    notice: belongsToCurrentUser ? notice : EMPTY_NOTICE,
    contractAvailable: belongsToCurrentUser && contractAvailable,
    canRetry: belongsToCurrentUser && canRetry,
    retry,
    dismiss,
  };
}
