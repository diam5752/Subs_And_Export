import React from "react";
import { Spinner } from "@/components/Spinner";
import type { useI18n } from "@/context/I18nContext";
import type { BillingPurchaseResponse } from "@/lib/api";

type Translate = ReturnType<typeof useI18n>["t"];
type DownloadArtifact = (endpoint: string | null, filename: string) => void;

function ArtifactButton({
  endpoint,
  filename,
  label,
  onDownload,
}: {
  endpoint: string | null;
  filename: string;
  label: string;
  onDownload: DownloadArtifact;
}) {
  if (!endpoint) return null;
  return (
    <button
      type="button"
      onClick={() => onDownload(endpoint, filename)}
      className="min-h-11 rounded-xl border border-[var(--border)] px-4 text-sm font-semibold hover:bg-black/[0.03]"
    >
      {label}
    </button>
  );
}

function WithdrawalResolution({
  purchase,
  onDownload,
  t,
}: {
  purchase: BillingPurchaseResponse;
  onDownload: DownloadArtifact;
  t: Translate;
}) {
  const accepted =
    purchase.withdrawal_resolution_decision === "accepted_refunded";
  const statusClassName = accepted
    ? "border-emerald-300 bg-emerald-50 text-emerald-950"
    : "border-amber-300 bg-amber-50 text-amber-950";
  return (
    <div className="space-y-3">
      <p
        className={`rounded-xl border p-4 text-sm font-semibold leading-6 ${statusClassName}`}
      >
        {t(
          accepted ? "billingWithdrawalAccepted" : "billingWithdrawalRejected",
        )}
      </p>
      <div className="flex flex-wrap gap-3">
        <ArtifactButton
          endpoint={purchase.withdrawal_acknowledgement_url}
          filename={`gsubs-withdrawal-${purchase.purchase_id}.json`}
          label={t("billingWithdrawalDownload")}
          onDownload={onDownload}
        />
        <ArtifactButton
          endpoint={purchase.withdrawal_resolution_url}
          filename={`gsubs-withdrawal-resolution-${purchase.purchase_id}.json`}
          label={t("billingWithdrawalResolutionDownload")}
          onDownload={onDownload}
        />
      </div>
    </div>
  );
}

function PendingWithdrawal({
  purchase,
  onDownload,
  t,
}: {
  purchase: BillingPurchaseResponse;
  onDownload: DownloadArtifact;
  t: Translate;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm leading-6 text-amber-800">
        {t("billingWithdrawalPending")}
      </p>
      <ArtifactButton
        endpoint={purchase.withdrawal_acknowledgement_url}
        filename={`gsubs-withdrawal-${purchase.purchase_id}.json`}
        label={t("billingWithdrawalDownload")}
        onDownload={onDownload}
      />
    </div>
  );
}

function WithdrawalForm({
  purchase,
  locale,
  confirmedName,
  confirmationEmail,
  submitting,
  nameInputRef,
  onSubmit,
  onNameChange,
  onEmailChange,
  onCancel,
  t,
}: {
  purchase: BillingPurchaseResponse;
  locale: string;
  confirmedName: string;
  confirmationEmail: string;
  submitting: boolean;
  nameInputRef: React.RefObject<HTMLInputElement | null>;
  onSubmit: React.FormEventHandler<HTMLFormElement>;
  onNameChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onCancel: (purchaseId: string) => void;
  t: Translate;
}) {
  const concludedAt =
    purchase.contract_concluded_at === null
      ? "—"
      : new Date(purchase.contract_concluded_at * 1000).toLocaleString(locale);
  return (
    <form className="space-y-4" onSubmit={onSubmit}>
      <h3 className="font-bold">{t("billingWithdrawalConfirmTitle")}</h3>
      <div className="space-y-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-950">
        <p className="font-semibold">
          {t("billingWithdrawalStatement", {
            purchaseId: purchase.purchase_id,
          })}
        </p>
        <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
          <dt>{t("billingWithdrawalPurchaseId")}</dt>
          <dd className="break-all font-mono">{purchase.purchase_id}</dd>
          <dt>{t("billingWithdrawalPackage")}</dt>
          <dd>{purchase.package_key}</dd>
          <dt>{t("billingWithdrawalConcludedAt")}</dt>
          <dd>{concludedAt}</dd>
        </dl>
      </div>
      <div>
        <label
          className="mb-2 block text-sm font-medium"
          htmlFor={`withdrawal-name-${purchase.purchase_id}`}
        >
          {t("billingWithdrawalName")}
        </label>
        <input
          ref={nameInputRef}
          id={`withdrawal-name-${purchase.purchase_id}`}
          value={confirmedName}
          onChange={(event) => onNameChange(event.target.value)}
          required
          maxLength={100}
          className="input-field"
        />
      </div>
      <div>
        <label
          className="mb-2 block text-sm font-medium"
          htmlFor={`withdrawal-email-${purchase.purchase_id}`}
        >
          {t("billingWithdrawalEmail")}
        </label>
        <input
          id={`withdrawal-email-${purchase.purchase_id}`}
          type="email"
          value={confirmationEmail}
          onChange={(event) => onEmailChange(event.target.value)}
          required
          maxLength={255}
          className="input-field"
        />
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          type="submit"
          disabled={submitting}
          className="btn-primary min-h-11"
        >
          {submitting && <Spinner className="mr-2 h-4 w-4" />}
          {t("billingWithdrawalConfirm")}
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={() => onCancel(purchase.purchase_id)}
          className="min-h-11 rounded-xl border border-[var(--border)] px-4 font-semibold"
        >
          {t("billingWithdrawalCancel")}
        </button>
      </div>
    </form>
  );
}

function WithdrawalStartButton({
  purchaseId,
  startButtonsRef,
  onBegin,
  t,
}: {
  purchaseId: string;
  startButtonsRef: React.RefObject<Map<string, HTMLButtonElement>>;
  onBegin: (purchaseId: string) => void;
  t: Translate;
}) {
  return (
    <button
      ref={(element) => {
        if (element) startButtonsRef.current.set(purchaseId, element);
        else startButtonsRef.current.delete(purchaseId);
      }}
      type="button"
      onClick={() => onBegin(purchaseId)}
      className="min-h-11 rounded-xl border border-red-300 px-4 text-sm font-bold text-red-700 hover:bg-red-50"
    >
      {t("billingWithdrawalStart")}
    </button>
  );
}

function WithdrawalUnavailableMessage({
  purchase,
  t,
}: {
  purchase: BillingPurchaseResponse;
  t: Translate;
}) {
  const contractNotConcluded =
    !purchase.contract_confirmation_available ||
    purchase.contract_concluded_at === null;
  return (
    <p className="text-sm leading-6 text-[var(--muted)]">
      {t(
        contractNotConcluded
          ? "billingContractNotConcluded"
          : "billingWithdrawalUnavailable",
      )}
    </p>
  );
}

function WithdrawalBody(props: BillingPurchaseCardProps) {
  const { purchase } = props;
  if (purchase.withdrawal_resolution_available) {
    return (
      <WithdrawalResolution
        purchase={purchase}
        onDownload={props.onDownload}
        t={props.t}
      />
    );
  }
  if (purchase.withdrawal_status) {
    return (
      <PendingWithdrawal
        purchase={purchase}
        onDownload={props.onDownload}
        t={props.t}
      />
    );
  }
  if (!purchase.withdrawal_action_available) {
    return <WithdrawalUnavailableMessage purchase={purchase} t={props.t} />;
  }
  if (props.selectedPurchaseId !== purchase.purchase_id) {
    return (
      <WithdrawalStartButton
        purchaseId={purchase.purchase_id}
        startButtonsRef={props.startButtonsRef}
        onBegin={props.onBegin}
        t={props.t}
      />
    );
  }
  return (
    <WithdrawalForm
      purchase={purchase}
      locale={props.locale}
      confirmedName={props.confirmedName}
      confirmationEmail={props.confirmationEmail}
      submitting={props.submitting}
      nameInputRef={props.nameInputRef}
      onSubmit={props.onSubmit}
      onNameChange={props.onNameChange}
      onEmailChange={props.onEmailChange}
      onCancel={props.onCancel}
      t={props.t}
    />
  );
}

interface BillingPurchaseCardProps {
  purchase: BillingPurchaseResponse;
  selectedPurchaseId: string | null;
  locale: string;
  confirmedName: string;
  confirmationEmail: string;
  submitting: boolean;
  nameInputRef: React.RefObject<HTMLInputElement | null>;
  startButtonsRef: React.RefObject<Map<string, HTMLButtonElement>>;
  onDownload: DownloadArtifact;
  onSubmit: React.FormEventHandler<HTMLFormElement>;
  onNameChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onBegin: (purchaseId: string) => void;
  onCancel: (purchaseId: string) => void;
  t: Translate;
}

export function BillingPurchaseCard(props: BillingPurchaseCardProps) {
  const { purchase, locale, onDownload, t } = props;
  return (
    <article className="rounded-2xl border border-[var(--border)] bg-white p-5 shadow-sm sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted)]">
            {purchase.package_key}
          </p>
          <h2 className="mt-2 text-xl font-bold">
            €{(purchase.amount_eur_cents / 100).toFixed(2)}
            {" · "}
            {purchase.credits} credits
          </h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            {new Date(purchase.created_at * 1000).toLocaleString(locale)}
            {" · "}
            {purchase.status}
          </p>
        </div>
        <ArtifactButton
          endpoint={purchase.contract_confirmation_url}
          filename={`gsubs-contract-${purchase.purchase_id}.json`}
          label={t("billingContractDownload")}
          onDownload={onDownload}
        />
      </div>
      <div className="mt-5 border-t border-[var(--border)] pt-5">
        <WithdrawalBody {...props} />
      </div>
    </article>
  );
}
