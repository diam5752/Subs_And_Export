import { CoinsIcon } from "@/components/icons";
import { Spinner } from "@/components/Spinner";
import type { CreditPackage } from "@/lib/api";
import { formatPoints } from "@/lib/points";
import type { CreditPurchaseController } from "./useCreditPurchaseController";
import type { Translate } from "./creditPurchaseTypes";

interface ViewProps {
  controller: CreditPurchaseController;
  dialogRef: React.RefObject<HTMLDivElement | null>;
  closeButtonRef: React.RefObject<HTMLButtonElement | null>;
  isAuthenticated: boolean;
  requiredCredits: number;
  t: Translate;
}

export function CreditPurchaseDialogView({
  controller,
  dialogRef,
  closeButtonRef,
  isAuthenticated,
  requiredCredits,
  t,
}: ViewProps) {
  const closeFromBackdrop = () => {
    if (!controller.isCheckingOut) controller.close();
  };
  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="credit-purchase-title"
      tabIndex={-1}
      className="fixed inset-0 z-[80] flex items-end justify-center bg-black/65 px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] backdrop-blur-md sm:items-center sm:p-8"
      onClick={closeFromBackdrop}
      data-testid="credit-purchase-dialog"
    >
      <div
        className="relative max-h-[94dvh] w-full max-w-[680px] overflow-y-auto rounded-[26px] border border-white/10 bg-[#0a0b0e] text-white shadow-[0_30px_100px_rgba(0,0,0,0.65)]"
        onClick={(event) => event.stopPropagation()}
      >
        <DialogHeader
          controller={controller}
          closeButtonRef={closeButtonRef}
          t={t}
        />
        <DialogBody
          controller={controller}
          isAuthenticated={isAuthenticated}
          requiredCredits={requiredCredits}
          t={t}
        />
      </div>
    </div>
  );
}

function DialogHeader({
  controller,
  closeButtonRef,
  t,
}: {
  controller: CreditPurchaseController;
  closeButtonRef: React.RefObject<HTMLButtonElement | null>;
  t: Translate;
}) {
  return (
    <div className="sticky top-0 z-10 flex items-start justify-between gap-4 bg-[#0a0b0e]/95 px-5 pt-5 pb-3 backdrop-blur-xl sm:px-7 sm:pt-7">
      <div>
        <span className="text-[10px] font-bold uppercase tracking-[0.22em] text-sky-400">
          {t("creditPurchaseKicker")}
        </span>
        <h2
          id="credit-purchase-title"
          className="mt-2 text-2xl font-bold tracking-[-0.04em] sm:text-3xl"
        >
          {t("creditPurchaseTitle")}
        </h2>
      </div>
      <button
        ref={closeButtonRef}
        type="button"
        onClick={controller.close}
        disabled={controller.isCheckingOut}
        className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-white/15 text-[#9aa2ae] transition hover:border-white/25 hover:bg-white/5 hover:text-white disabled:opacity-40"
        aria-label={t("closeLabel")}
      >
        <span aria-hidden="true">✕</span>
      </button>
    </div>
  );
}

function DialogBody({
  controller,
  isAuthenticated,
  requiredCredits,
  t,
}: Omit<ViewProps, "dialogRef" | "closeButtonRef">) {
  return (
    <div className="space-y-5 px-5 pt-3 pb-5 sm:px-7 sm:pb-7">
      <BalanceSummary
        balance={controller.aiSpendableBalance}
        requiredCredits={requiredCredits}
        missingCredits={controller.missingCredits}
        reversalDebt={controller.reversalDebt}
        t={t}
      />
      <CatalogChoices controller={controller} t={t} />
      <StatusMessages controller={controller} t={t} />
      <ConsumerConsent controller={controller} t={t} />
      <CheckoutAction
        controller={controller}
        isAuthenticated={isAuthenticated}
        t={t}
      />
    </div>
  );
}

function BalanceSummary({
  balance,
  requiredCredits,
  missingCredits,
  reversalDebt,
  t,
}: {
  balance: number | null;
  requiredCredits: number;
  missingCredits: number;
  reversalDebt: number | null;
  t: Translate;
}) {
  return (
    <>
      <div
        data-testid="credit-purchase-available-balance"
        className="inline-flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.025] px-3.5 py-2.5"
      >
        <CoinsIcon className="h-4 w-4 text-sky-400" />
        <strong className="text-base text-white">
          {balance === null ? "—" : formatPoints(balance)}
        </strong>
        <span className="text-sm text-[#b2bac5]">
          {t("creditPurchaseAvailableNow")}
        </span>
      </div>
      {requiredCredits > 0 && (
        <RequiredCredits
          requiredCredits={requiredCredits}
          missingCredits={missingCredits}
          t={t}
        />
      )}
      {typeof reversalDebt === "number" && reversalDebt > 0 && (
        <p
          role="alert"
          className="rounded-2xl border border-amber-400/25 bg-amber-400/[0.08] px-4 py-3 text-sm leading-6 text-amber-100"
        >
          {t("creditPurchaseDebtNotice", { count: reversalDebt })}
        </p>
      )}
    </>
  );
}

function RequiredCredits({
  requiredCredits,
  missingCredits,
  t,
}: {
  requiredCredits: number;
  missingCredits: number;
  t: Translate;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-sky-400/25 bg-sky-400/[0.07] px-4 py-3">
      <span className="text-sm text-[#cbd4df]">
        {t("creditPurchaseRequired")}
      </span>
      <div className="flex items-center gap-4 text-sm">
        <span>
          {formatPoints(requiredCredits)} {t("creditsLabel")}
        </span>
        <strong className="text-sky-300">
          {t("creditPurchaseMissing", { count: missingCredits })}
        </strong>
      </div>
    </div>
  );
}

function packageLabel(packageKey: string, t: Translate): string {
  if (packageKey === "starter") return t("creditPackageStarter");
  if (packageKey === "core") return t("creditPackageCore");
  if (packageKey === "pro") return t("creditPackagePro");
  return packageKey;
}

function CatalogChoices({
  controller,
  t,
}: {
  controller: CreditPurchaseController;
  t: Translate;
}) {
  if (controller.isLoading) {
    return (
      <div className="grid min-h-52 place-items-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (!controller.paidSalesVisible) return null;
  return (
    <div
      role="radiogroup"
      aria-label={t("creditPurchasePackagesLabel")}
      className="grid grid-cols-3 gap-2.5"
    >
      {controller.catalog?.packages.map((creditPackage, index) => (
        <PackageOption
          key={creditPackage.key}
          creditPackage={creditPackage}
          packageLabel={packageLabel(creditPackage.key, t)}
          selected={creditPackage.key === controller.selectedKey}
          onSelect={() => controller.changePackage(creditPackage.key)}
          onKeyDown={(event) => controller.handlePackageKeyDown(event, index)}
          inputRef={(element) =>
            controller.registerPackageRadio(creditPackage.key, element)
          }
          creditsLabel={t("creditsLabel")}
        />
      ))}
    </div>
  );
}

function StatusMessages({
  controller,
  t,
}: {
  controller: CreditPurchaseController;
  t: Translate;
}) {
  return (
    <>
      {controller.catalog && !controller.paidSalesVisible && (
        <p
          role="status"
          className="rounded-2xl border border-amber-300/20 bg-amber-300/[0.07] px-4 py-3 text-sm leading-6 text-amber-100"
        >
          {t("creditPurchaseNotEnabled")}
        </p>
      )}
      {controller.error && (
        <p
          role="alert"
          className="rounded-2xl border border-red-400/25 bg-red-400/[0.08] px-4 py-3 text-sm text-red-100"
        >
          {controller.error}
        </p>
      )}
    </>
  );
}

function ConsumerConsent({
  controller,
  t,
}: {
  controller: CreditPurchaseController;
  t: Translate;
}) {
  const contract = controller.consumerContract;
  if (!controller.catalog || !contract || !controller.paidSalesVisible) {
    return null;
  }
  return (
    <div className="space-y-4">
      <PurchaseFacts controller={controller} t={t} />
      <div className="flex items-start gap-3">
        <input
          id={controller.combinedConsentId}
          type="checkbox"
          checked={controller.combinedConsentAccepted}
          aria-describedby={controller.consentConsequenceId}
          onChange={(event) => controller.updateConsent(event.target.checked)}
          className="mt-0.5 h-5 w-5 shrink-0 rounded border-white/20 accent-sky-400"
        />
        <ConsentDescription controller={controller} contract={contract} t={t} />
      </div>
    </div>
  );
}

function PurchaseFacts({
  controller,
  t,
}: {
  controller: CreditPurchaseController;
  t: Translate;
}) {
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-x-2.5 gap-y-2 border-y border-white/10 py-3 text-xs text-[#9da6b2]"
    >
      <span>{t("creditPurchaseBillingScope")}</span>
      <span aria-hidden="true">·</span>
      <span>{t("creditPurchaseVatIncluded")}</span>
      <span aria-hidden="true">·</span>
      <span>{t("creditPurchaseOneOff")}</span>
      <span
        className="hidden h-4 w-px bg-white/10 sm:block"
        aria-hidden="true"
      />
      <LegalLink
        href={controller.paidCreditsTermsUrl}
        label={t("creditPurchaseTermsLink")}
      />
      <LegalLink
        href={controller.withdrawalRightsUrl}
        label={t("creditPurchaseWithdrawalDetailsLink")}
      />
    </div>
  );
}

function LegalLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-semibold text-white underline decoration-white/30 underline-offset-4 transition hover:decoration-white"
    >
      {label}
    </a>
  );
}

function ConsentDescription({
  controller,
  contract,
  t,
}: {
  controller: CreditPurchaseController;
  contract: NonNullable<CreditPurchaseController["consumerContract"]>;
  t: Translate;
}) {
  return (
    <div>
      <label
        htmlFor={controller.combinedConsentId}
        className="cursor-pointer text-sm font-medium leading-5 text-[#e6eaf0]"
      >
        {t("creditPurchaseConsentRequest")}
      </label>
      <p
        id={controller.consentConsequenceId}
        className="mt-1 text-xs leading-5 text-[#8f98a5]"
      >
        {t("creditPurchaseConsentConsequence")}
      </p>
      <details className="group mt-1.5 text-xs text-[#8f98a5]">
        <summary className="inline-flex cursor-pointer list-none items-center gap-1 font-medium text-[#c8d0da] underline decoration-white/20 underline-offset-4 transition hover:text-white [&::-webkit-details-marker]:hidden">
          {t("creditPurchaseExactConsentDetails")}
          <span
            aria-hidden="true"
            className="text-[10px] transition group-open:rotate-180"
          >
            ▾
          </span>
        </summary>
        <ul className="mt-2 space-y-1.5 border-l border-white/10 pl-4 text-[11px] leading-5">
          {Object.entries(contract.required_acceptances).map(
            ([key, acceptance]) => (
              <li key={key}>{acceptance}</li>
            ),
          )}
        </ul>
      </details>
    </div>
  );
}

function checkoutButtonLabel(
  isAuthenticated: boolean,
  selectedPackage: CreditPackage | null,
  t: Translate,
): string {
  if (!isAuthenticated) return t("creditPurchaseSignIn");
  if (!selectedPackage) return t("creditPurchaseContinue");
  return t("creditPurchaseContinueToPayment", {
    amount: (selectedPackage.amount_eur_cents / 100).toFixed(2),
  });
}

function CheckoutAction({
  controller,
  isAuthenticated,
  t,
}: {
  controller: CreditPurchaseController;
  isAuthenticated: boolean;
  t: Translate;
}) {
  if (!controller.paidSalesVisible) return null;
  const selectionMissing =
    isAuthenticated &&
    (!controller.selectedPackage || !controller.combinedConsentAccepted);
  return (
    <div className="flex flex-col border-t border-white/10 pt-5 sm:flex-row sm:justify-end">
      <button
        type="button"
        onClick={() => void controller.handleCheckout()}
        disabled={
          controller.isCheckingOut || controller.isLoading || selectionMissing
        }
        className="inline-flex min-h-12 shrink-0 items-center justify-center gap-2 rounded-xl bg-sky-500 px-5 text-sm font-bold text-[#061018] shadow-[0_14px_36px_rgba(14,165,233,0.18)] transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {controller.isCheckingOut && <Spinner className="h-4 w-4" />}
        {checkoutButtonLabel(isAuthenticated, controller.selectedPackage, t)}
      </button>
    </div>
  );
}

function PackageOption({
  creditPackage,
  packageLabel,
  selected,
  onSelect,
  onKeyDown,
  inputRef,
  creditsLabel,
}: {
  creditPackage: CreditPackage;
  packageLabel: string;
  selected: boolean;
  onSelect: () => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  inputRef: (element: HTMLInputElement | null) => void;
  creditsLabel: string;
}) {
  return (
    <label className="block cursor-pointer">
      <input
        ref={inputRef}
        type="radio"
        name="credit-package"
        value={creditPackage.key}
        checked={selected}
        onChange={onSelect}
        onKeyDown={onKeyDown}
        className="peer sr-only"
      />
      <span
        className={`relative block min-h-36 rounded-2xl border p-3.5 text-left transition sm:p-4 peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-sky-300 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-[#0a0b0e] ${selected ? "border-sky-400 bg-sky-400/[0.09] shadow-[0_0_0_1px_rgba(56,189,248,0.25)]" : "border-white/10 bg-white/[0.025] hover:border-white/20 hover:bg-white/[0.045]"}`}
      >
        <span className="block truncate text-[10px] font-bold uppercase tracking-[0.16em] text-[#8d96a3] sm:text-xs">
          {packageLabel}
        </span>
        <strong className="mt-5 block text-2xl tracking-[-0.05em] sm:text-3xl">
          €{(creditPackage.amount_eur_cents / 100).toFixed(2)}
        </strong>
        <span className="mt-3 flex items-center gap-1.5 text-[11px] font-medium text-[#cbd3dc] sm:text-sm">
          <CoinsIcon className="hidden h-3.5 w-3.5 text-sky-300 sm:block" />
          {formatPoints(creditPackage.credits)} {creditsLabel}
        </span>
      </span>
    </label>
  );
}
