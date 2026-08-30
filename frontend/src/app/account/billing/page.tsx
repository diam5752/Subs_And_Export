"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { api, type BillingPurchaseResponse } from "@/lib/api";
import { BillingAccountView } from "./BillingAccountView";

function withdrawalIdempotencyKey(): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `withdrawal-${random}`;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.URL.revokeObjectURL(url);
}

function useWithdrawalFocus(selectedPurchaseId: string | null, notice: string) {
  const nameInputRef = useRef<HTMLInputElement>(null);
  const startButtonsRef = useRef(new Map<string, HTMLButtonElement>());
  const restoreStartFocusForRef = useRef<string | null>(null);
  const focusSuccessNoticeRef = useRef(false);
  const noticeRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (selectedPurchaseId) {
      queueMicrotask(() => nameInputRef.current?.focus());
      return;
    }
    const purchaseId = restoreStartFocusForRef.current;
    if (!purchaseId) return;
    restoreStartFocusForRef.current = null;
    queueMicrotask(() => startButtonsRef.current.get(purchaseId)?.focus());
  }, [selectedPurchaseId]);
  useEffect(() => {
    if (!notice || !focusSuccessNoticeRef.current) return;
    focusSuccessNoticeRef.current = false;
    queueMicrotask(() => noticeRef.current?.focus());
  }, [notice]);
  const markSuccessNoticeForFocus = () => {
    focusSuccessNoticeRef.current = true;
  };
  const restoreStartFocusFor = (purchaseId: string) => {
    restoreStartFocusForRef.current = purchaseId;
  };
  return {
    nameInputRef,
    startButtonsRef,
    noticeRef,
    markSuccessNoticeForFocus,
    restoreStartFocusFor,
  };
}

export default function BillingAccountPage() {
  const { user, isLoading: authLoading } = useAuth();
  const { locale, t } = useI18n();
  const [purchases, setPurchases] = useState<BillingPurchaseResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedPurchaseId, setSelectedPurchaseId] = useState<string | null>(
    null,
  );
  const [confirmedName, setConfirmedName] = useState("");
  const [confirmationEmail, setConfirmationEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const withdrawalKeyRef = useRef(withdrawalIdempotencyKey());
  const withdrawalFocus = useWithdrawalFocus(selectedPurchaseId, notice);

  const loadPurchases = useCallback(async () => {
    if (!user) {
      setPurchases([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setPurchases(await api.listBillingPurchases());
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : t("billingPageLoadError"),
      );
    } finally {
      setLoading(false);
    }
  }, [t, user]);

  useEffect(() => {
    if (authLoading) return;
    const loadTimer = window.setTimeout(() => {
      void loadPurchases();
    }, 0);
    return () => window.clearTimeout(loadTimer);
  }, [authLoading, loadPurchases]);

  const beginWithdrawal = (purchaseId: string) => {
    if (!user) return;
    setSelectedPurchaseId(purchaseId);
    setConfirmedName(user.name);
    setConfirmationEmail(user.email);
    setError("");
    setNotice("");
    withdrawalKeyRef.current = withdrawalIdempotencyKey();
  };

  const submitWithdrawal = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedPurchaseId) return;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      await api.submitBillingWithdrawal(
        selectedPurchaseId,
        {
          locale,
          withdrawal_requested: true,
          confirmed_name: confirmedName,
          confirmation_email: confirmationEmail,
        },
        withdrawalKeyRef.current,
      );
      withdrawalFocus.markSuccessNoticeForFocus();
      setSelectedPurchaseId(null);
      setNotice(t("billingWithdrawalPending"));
      await loadPurchases();
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : t("billingWithdrawalError"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const downloadArtifact = async (
    endpoint: string | null,
    filename: string,
  ) => {
    if (!endpoint) return;
    setError("");
    try {
      const artifact = await api.downloadBillingArtifact(endpoint);
      downloadBlob(artifact, filename);
    } catch (downloadError) {
      setError(
        downloadError instanceof Error
          ? downloadError.message
          : t("billingArtifactError"),
      );
    }
  };

  const handleDownload = (endpoint: string | null, filename: string) => {
    void downloadArtifact(endpoint, filename);
  };

  const cancelWithdrawal = (purchaseId: string) => {
    withdrawalFocus.restoreStartFocusFor(purchaseId);
    setSelectedPurchaseId(null);
  };

  return (
    <BillingAccountView
      user={user}
      authLoading={authLoading}
      loading={loading}
      purchases={purchases}
      error={error}
      notice={notice}
      noticeRef={withdrawalFocus.noticeRef}
      selectedPurchaseId={selectedPurchaseId}
      locale={locale}
      confirmedName={confirmedName}
      confirmationEmail={confirmationEmail}
      submitting={submitting}
      nameInputRef={withdrawalFocus.nameInputRef}
      startButtonsRef={withdrawalFocus.startButtonsRef}
      onDownload={handleDownload}
      onSubmit={submitWithdrawal}
      onNameChange={setConfirmedName}
      onEmailChange={setConfirmationEmail}
      onBegin={beginWithdrawal}
      onCancel={cancelWithdrawal}
      t={t}
    />
  );
}
