"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ProcessingGateAuthStage,
  ProcessingGateCostStage,
} from "@/components/ProcessingGateStages";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { useDocumentScrollLock } from "@/hooks/useDocumentScrollLock";

export type ProcessingGateStage = "auth" | "cost";

interface ProcessingGateModalProps {
  isOpen: boolean;
  stage: ProcessingGateStage;
  initialScrollPosition?: { x: number; y: number };
  cost: number;
  balance: number | null;
  requiresPaidCredits?: boolean;
  isBalanceLoading: boolean;
  error: string;
  onClose: () => void;
  onAuthenticated: () => Promise<void>;
  onConfirm: () => Promise<void>;
  onPurchaseCredits?: () => void;
}

function visibleFocusableElements(dialog: HTMLDivElement): HTMLElement[] {
  return Array.from(
    dialog.querySelectorAll<HTMLElement>(
      "a[href], button:not([disabled]), input:not([disabled]), " +
        "select:not([disabled]), textarea:not([disabled]), " +
        '[tabindex]:not([tabindex="-1"])',
    ),
  ).filter(
    (element) =>
      element.getAttribute("aria-hidden") !== "true" &&
      element.getClientRects().length > 0,
  );
}

function trapDialogTab(event: KeyboardEvent, dialog: HTMLDivElement): void {
  const focusable = visibleFocusableElements(dialog);
  if (focusable.length === 0) {
    event.preventDefault();
    dialog.focus({ preventScroll: true });
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const activeElement = document.activeElement;
  const outsideDialog = !dialog.contains(activeElement);
  if (event.shiftKey && (activeElement === first || outsideDialog)) {
    event.preventDefault();
    last.focus({ preventScroll: true });
    return;
  }
  if (!event.shiftKey && (activeElement === last || outsideDialog)) {
    event.preventDefault();
    first.focus({ preventScroll: true });
  }
}

export function ProcessingGateModal({
  isOpen,
  stage,
  initialScrollPosition,
  cost,
  balance,
  requiresPaidCredits = true,
  isBalanceLoading,
  error,
  onClose,
  onAuthenticated,
  onConfirm,
  onPurchaseCredits,
}: ProcessingGateModalProps) {
  const { login, register } = useAuth();
  const { t } = useI18n();
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCostActionPending, setIsCostActionPending] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const costActionRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const authSessionGenerationRef = useRef(0);
  const costActionInFlightRef = useRef(false);

  const close = useCallback(() => onClose(), [onClose]);

  const confirmCostAction = useCallback(async () => {
    if (costActionInFlightRef.current || isBalanceLoading) return;
    costActionInFlightRef.current = true;
    setIsCostActionPending(true);
    try {
      await onConfirm();
    } finally {
      costActionInFlightRef.current = false;
      setIsCostActionPending(false);
    }
  }, [isBalanceLoading, onConfirm]);

  const purchaseCredits = useCallback(() => {
    if (costActionInFlightRef.current || isBalanceLoading || !onPurchaseCredits)
      return;
    costActionInFlightRef.current = true;
    setIsCostActionPending(true);
    onPurchaseCredits();
  }, [isBalanceLoading, onPurchaseCredits]);

  useEffect(() => {
    if (!isOpen) return;
    const sessionGeneration = authSessionGenerationRef.current + 1;
    authSessionGenerationRef.current = sessionGeneration;
    return () => {
      if (authSessionGenerationRef.current === sessionGeneration) {
        authSessionGenerationRef.current += 1;
      }
    };
  }, [isOpen]);

  useDocumentScrollLock(isOpen, initialScrollPosition);

  useEffect(() => {
    if (!isOpen) return;
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key === "Tab" && dialogRef.current) {
        trapDialogTab(event, dialogRef.current);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      const returnTarget = returnFocusRef.current;
      returnFocusRef.current = null;
      queueMicrotask(() => {
        if (returnTarget?.isConnected) {
          returnTarget.focus({ preventScroll: true });
        }
      });
    };
  }, [close, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    if (stage === "auth") {
      emailRef.current?.focus({ preventScroll: true });
      return;
    }
    const costAction = costActionRef.current;
    if (costAction && !costAction.disabled) {
      costAction.focus({ preventScroll: true });
    } else {
      closeButtonRef.current?.focus({ preventScroll: true });
    }
  }, [isOpen, stage]);

  const handleAuthSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const sessionGeneration = authSessionGenerationRef.current;
    setAuthError("");
    setIsSubmitting(true);
    try {
      if (authMode === "register") {
        await register(email, password, name);
      } else {
        await login(email, password);
      }
      if (sessionGeneration !== authSessionGenerationRef.current) return;
      await onAuthenticated();
    } catch (authFailure) {
      if (sessionGeneration === authSessionGenerationRef.current) {
        setAuthError(
          authFailure instanceof Error
            ? authFailure.message
            : t("processingGateAuthError"),
        );
      }
    } finally {
      if (sessionGeneration === authSessionGenerationRef.current) {
        setIsSubmitting(false);
      }
    }
  };

  const toggleAuthMode = () => {
    setAuthMode((mode) => (mode === "login" ? "register" : "login"));
    setAuthError("");
  };

  if (!isOpen) return null;
  const isAuthStage = stage === "auth";
  const title = isAuthStage
    ? t("processingGateAuthTitle")
    : t("processingGateCostTitle");

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="processing-gate-title"
      aria-describedby="processing-gate-description"
      className="fixed inset-0 z-[70] flex items-end justify-center overflow-y-auto overscroll-contain bg-black/55 px-4 pt-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] backdrop-blur-sm sm:items-center sm:py-8"
      onClick={close}
      data-testid="processing-gate"
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="relative max-h-full w-full max-w-md overflow-x-hidden overflow-y-auto overscroll-contain rounded-[24px] border border-black/10 bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        data-testid="processing-gate-card"
      >
        <div className="h-1 bg-[var(--accent)]" />
        <div className="p-6 sm:p-8">
          <div className="mb-6 flex items-start justify-between gap-4">
            <div>
              <span className="mb-2 block text-[11px] font-bold uppercase tracking-[0.18em] text-[var(--accent)]">
                {isAuthStage
                  ? t("processingGateAuthKicker")
                  : t("processingGateCostKicker")}
              </span>
              <h2
                id="processing-gate-title"
                className="text-2xl font-bold tracking-[-0.04em] text-[var(--foreground)]"
              >
                {title}
              </h2>
              <p
                id="processing-gate-description"
                className="mt-2 text-sm leading-6 text-[var(--muted)]"
              >
                {isAuthStage
                  ? t("processingGateAuthDescription")
                  : t("processingGateCostDescription")}
              </p>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={close}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-[var(--border)] text-[var(--muted)] transition-colors hover:bg-[#f5f5f4] hover:text-[var(--foreground)]"
              aria-label={t("closeLabel")}
            >
              <span aria-hidden="true">✕</span>
            </button>
          </div>
          {isAuthStage ? (
            <ProcessingGateAuthStage
              authMode={authMode}
              name={name}
              email={email}
              password={password}
              authError={authError}
              error={error}
              isSubmitting={isSubmitting}
              emailRef={emailRef}
              onAuthenticated={onAuthenticated}
              onSubmit={(event) => void handleAuthSubmit(event)}
              onNameChange={setName}
              onEmailChange={setEmail}
              onPasswordChange={setPassword}
              onToggleMode={toggleAuthMode}
              t={t}
            />
          ) : (
            <ProcessingGateCostStage
              cost={cost}
              balance={balance}
              requiresPaidCredits={requiresPaidCredits}
              isBalanceLoading={isBalanceLoading}
              error={error}
              isPending={isCostActionPending}
              actionRef={costActionRef}
              onClose={close}
              onConfirm={() => void confirmCostAction()}
              onPurchaseCredits={
                onPurchaseCredits ? purchaseCredits : undefined
              }
              t={t}
            />
          )}
        </div>
      </div>
    </div>
  );
}
