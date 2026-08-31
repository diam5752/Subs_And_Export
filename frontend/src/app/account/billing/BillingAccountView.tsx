import Link from "next/link";
import type { FormEventHandler, RefObject } from "react";
import { BetaBrandLogo } from "@/components/BetaBrandLogo";
import { Spinner } from "@/components/Spinner";
import type { User } from "@/context/AuthContext";
import type { useI18n } from "@/context/I18nContext";
import type { BillingPurchaseResponse } from "@/lib/api";
import { paidCreditLegalPublicationIsApproved } from "@/lib/paidCreditLegal";
import { BillingPurchaseCard } from "./BillingPurchaseCard";

type Translate = ReturnType<typeof useI18n>["t"];

interface BillingAccountViewProps {
  user: User | null;
  authLoading: boolean;
  loading: boolean;
  purchases: BillingPurchaseResponse[];
  error: string;
  notice: string;
  noticeRef: RefObject<HTMLParagraphElement | null>;
  selectedPurchaseId: string | null;
  locale: string;
  confirmedName: string;
  confirmationEmail: string;
  submitting: boolean;
  nameInputRef: RefObject<HTMLInputElement | null>;
  startButtonsRef: RefObject<Map<string, HTMLButtonElement>>;
  onDownload: (endpoint: string | null, filename: string) => void;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onNameChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onBegin: (purchaseId: string) => void;
  onCancel: (purchaseId: string) => void;
  t: Translate;
}

function BillingPageHeader({ t }: Pick<BillingAccountViewProps, "t">) {
  return (
    <header className="border-b border-[#e7e7e5] bg-[#f7f7f5]">
      <div className="mx-auto flex min-h-[72px] w-full max-w-5xl items-center justify-between gap-4 px-5 sm:px-8">
        <Link href="/" aria-label={t("brandHomeLabel")}>
          <BetaBrandLogo className="block h-auto w-[68px] sm:w-[72px]" />
        </Link>
        <Link
          href="/"
          className="text-sm font-semibold text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          {t("billingPageBack")}
        </Link>
      </div>
    </header>
  );
}

function BillingNotices({
  error,
  notice,
  noticeRef,
}: Pick<BillingAccountViewProps, "error" | "notice" | "noticeRef">) {
  return (
    <>
      {error && (
        <p
          role="alert"
          className="mt-6 rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-800"
        >
          {error}
        </p>
      )}
      {notice && (
        <p
          ref={noticeRef}
          role="status"
          tabIndex={-1}
          className="mt-6 rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
        >
          {notice}
        </p>
      )}
    </>
  );
}

function BillingPurchaseList(props: BillingAccountViewProps) {
  if (props.authLoading || props.loading) {
    return (
      <div className="grid min-h-52 place-items-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (!props.user) {
    return (
      <div className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-6">
        <p>{props.t("billingPageSignIn")}</p>
        <Link
          href="/login"
          className="mt-4 inline-flex font-semibold text-[var(--accent)] underline"
        >
          {props.t("loginSubmit")}
        </Link>
      </div>
    );
  }
  if (props.purchases.length === 0) {
    return (
      <p className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-6">
        {props.t("billingPageEmpty")}
      </p>
    );
  }
  return (
    <div className="mt-8 space-y-5">
      {props.purchases.map((purchase) => (
        <BillingPurchaseCard
          key={purchase.purchase_id}
          purchase={purchase}
          selectedPurchaseId={props.selectedPurchaseId}
          locale={props.locale}
          confirmedName={props.confirmedName}
          confirmationEmail={props.confirmationEmail}
          submitting={props.submitting}
          nameInputRef={props.nameInputRef}
          startButtonsRef={props.startButtonsRef}
          onDownload={props.onDownload}
          onSubmit={props.onSubmit}
          onNameChange={props.onNameChange}
          onEmailChange={props.onEmailChange}
          onBegin={props.onBegin}
          onCancel={props.onCancel}
          t={props.t}
        />
      ))}
    </div>
  );
}

export function BillingAccountView(props: BillingAccountViewProps) {
  return (
    <div className="min-h-dvh bg-[#f7f7f5] text-[var(--foreground)]">
      <BillingPageHeader t={props.t} />
      <main className="mx-auto w-full max-w-4xl px-5 py-10 sm:px-8 sm:py-16">
        <p className="text-xs font-bold tracking-[0.18em] text-[var(--accent)]">
          {props.t("billingPageKicker")}
        </p>
        <h1 className="mt-3 text-4xl font-extrabold tracking-[-0.045em] sm:text-5xl">
          {props.t("billingPageTitle")}
        </h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-[var(--muted)]">
          {props.t("billingPageDescription")}
        </p>
        <BillingNotices {...props} />
        <BillingPurchaseList {...props} />
        {paidCreditLegalPublicationIsApproved() && (
          <Link
            href="/terms#withdrawal"
            className="mt-8 inline-flex text-sm font-semibold text-[var(--accent)] underline"
          >
            {props.t("creditPurchaseWithdrawalFormLink")}
          </Link>
        )}
      </main>
    </div>
  );
}
