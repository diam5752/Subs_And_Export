import React from "react";
import { CoinsIcon } from "@/components/icons";
import { Spinner } from "@/components/Spinner";
import type { useI18n } from "@/context/I18nContext";
import { formatPoints } from "@/lib/points";

export { ProcessingGateAuthStage } from "./ProcessingGateAuthStage";

type Translate = ReturnType<typeof useI18n>["t"];

interface ProcessingGateCostStageProps {
  cost: number;
  balance: number | null;
  requiresPaidCredits: boolean;
  isBalanceLoading: boolean;
  error: string;
  isPending: boolean;
  actionRef: React.RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  onConfirm: () => void;
  onPurchaseCredits?: () => void;
  t: Translate;
}

function CostAction({
  canAfford,
  onPurchaseCredits,
  onConfirm,
  t,
  cost,
  actionRef,
  isBalanceLoading,
  isPending,
}: ProcessingGateCostStageProps & { canAfford: boolean }) {
  if (!canAfford && !onPurchaseCredits) return null;
  const clickAction = canAfford ? onConfirm : onPurchaseCredits;
  const label = canAfford
    ? t("processingGateConfirm", { cost })
    : t("processingGateBuyCredits");
  return (
    <button
      ref={actionRef}
      type="button"
      onClick={clickAction}
      disabled={isBalanceLoading || isPending}
      aria-busy={isPending}
      className="btn-primary flex min-h-12 items-center justify-center gap-2 px-4 disabled:cursor-not-allowed disabled:opacity-45"
    >
      {isPending && <Spinner className="h-4 w-4" />}
      {label}
    </button>
  );
}

function CostSummary(props: ProcessingGateCostStageProps) {
  const balanceLabel = props.requiresPaidCredits
    ? "processingGateBalanceLabel"
    : "processingGateTotalBalanceLabel";
  return (
    <div className="rounded-2xl border border-[#e7dfbd] bg-[#fffdf3] p-5">
      <div className="flex items-center justify-between gap-4">
        <span className="text-sm font-medium text-[var(--muted)]">
          {props.t("processingGateCostLabel")}
        </span>
        <span className="flex items-center gap-2 text-2xl font-bold text-[var(--foreground)]">
          <CoinsIcon className="h-6 w-6 text-[#c99a00]" />
          {formatPoints(props.cost)}
        </span>
      </div>
      <div className="my-4 h-px bg-[#ece4c8]" />
      <div className="flex items-center justify-between gap-4 text-sm">
        <span className="text-[var(--muted)]">{props.t(balanceLabel)}</span>
        <strong className="text-[var(--foreground)]">
          {props.isBalanceLoading || props.balance === null
            ? "—"
            : formatPoints(props.balance)}
        </strong>
      </div>
    </div>
  );
}

function CostMessages(
  props: ProcessingGateCostStageProps & { canAfford: boolean },
) {
  const showInsufficient =
    !props.isBalanceLoading && props.balance !== null && !props.canAfford;
  const missingPoints =
    props.balance === null ? 0 : Math.max(0, props.cost - props.balance);
  return (
    <>
      {props.error && (
        <p
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {props.error}
        </p>
      )}
      {showInsufficient && (
        <p
          role="alert"
          className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          {props.t("processingGateInsufficient", { count: missingPoints })}
        </p>
      )}
      <p className="text-xs leading-5 text-[var(--muted)]">
        {props.t(
          props.requiresPaidCredits
            ? "processingGateChargeNote"
            : "processingGateLocalChargeNote",
        )}
      </p>
    </>
  );
}

export function ProcessingGateCostStage(props: ProcessingGateCostStageProps) {
  const canAfford = props.balance !== null && props.balance >= props.cost;
  const columnsClassName =
    canAfford || props.onPurchaseCredits ? "sm:grid-cols-2" : "";
  return (
    <div className="space-y-5">
      <CostSummary {...props} />
      <CostMessages {...props} canAfford={canAfford} />
      <div className={`grid grid-cols-1 gap-3 ${columnsClassName}`}>
        <button
          type="button"
          onClick={props.onClose}
          className="min-h-12 rounded-xl border border-[var(--border)] bg-white px-4 font-semibold text-[var(--foreground)] hover:bg-[#f5f5f4]"
        >
          {props.t("processingGateCancel")}
        </button>
        <CostAction {...props} canAfford={canAfford} />
      </div>
    </div>
  );
}
