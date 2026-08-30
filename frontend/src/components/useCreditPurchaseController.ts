import { useCallback, useEffect, useId, useRef, useState } from "react";
import { usePoints } from "@/context/PointsContext";
import { useDocumentScrollLock } from "@/hooks/useDocumentScrollLock";
import { api, type CreditCatalogResponse, type CreditPackage } from "@/lib/api";
import { paidCreditLegalPublicationIsApproved } from "@/lib/paidCreditLegal";
import {
  checkoutIdempotencyKey,
  contractDisclosureIdentity,
  focusableElements,
  isAllowedStripeCheckoutUrl,
  packageIndexForKey,
} from "./creditPurchaseSupport";
import type {
  ConsumerContract,
  ContractConsentState,
  I18nValue,
  OpenCreditPurchaseDialogProps,
  Translate,
} from "./creditPurchaseTypes";

interface CatalogState {
  catalog: CreditCatalogResponse | null;
  selectedKey: string;
  consentState: ContractConsentState | null;
  isLoading: boolean;
  error: string;
  setSelectedKey: (key: string) => void;
  setConsentState: (state: ContractConsentState | null) => void;
  setError: (error: string) => void;
}

interface PurchaseDerivedState {
  selectedPackage: CreditPackage | null;
  consumerContract: ConsumerContract | null;
  paidSalesAvailable: boolean;
  paidSalesVisible: boolean;
  disclosureIdentity: string | null;
  combinedConsentAccepted: boolean;
  termsBaseUrl: string;
}

interface PackageInteractions {
  changePackage: (packageKey: string) => void;
  updateConsent: (checked: boolean) => void;
  handlePackageKeyDown: CreditPurchaseController["handlePackageKeyDown"];
  registerPackageRadio: CreditPurchaseController["registerPackageRadio"];
}

export interface CreditPurchaseController {
  aiSpendableBalance: number | null;
  reversalDebt: number | null;
  catalog: CreditCatalogResponse | null;
  selectedPackage: CreditPackage | null;
  selectedKey: string;
  consumerContract: ConsumerContract | null;
  paidSalesVisible: boolean;
  combinedConsentAccepted: boolean;
  paidCreditsTermsUrl: string;
  withdrawalRightsUrl: string;
  missingCredits: number;
  isLoading: boolean;
  isCheckingOut: boolean;
  error: string;
  combinedConsentId: string;
  consentConsequenceId: string;
  close: () => void;
  changePackage: (packageKey: string) => void;
  updateConsent: (checked: boolean) => void;
  handlePackageKeyDown: (
    event: React.KeyboardEvent<HTMLInputElement>,
    packageIndex: number,
  ) => void;
  registerPackageRadio: (
    packageKey: string,
    element: HTMLInputElement | null,
  ) => void;
  handleCheckout: () => Promise<void>;
}

function recommendedPackageKey(
  catalog: CreditCatalogResponse,
  recommendationGap: number,
): string {
  const recommended =
    catalog.packages.find((item) => item.credits >= recommendationGap) ??
    catalog.packages[catalog.packages.length - 1];
  return recommended?.key ?? "";
}

function creditGap(requiredCredits: number, balance: number | null): number {
  return Math.max(0, requiredCredits - (balance ?? 0));
}

function useCreditCatalog(
  locale: I18nValue["locale"],
  t: Translate,
  recommendationGap: number,
): CatalogState {
  const [catalog, setCatalog] = useState<CreditCatalogResponse | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [consentState, setConsentState] = useState<ContractConsentState | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const recommendationGapRef = useRef(recommendationGap);

  useEffect(() => {
    let active = true;
    void api
      .getCreditCatalog(locale)
      .then((result) => {
        if (!active) return;
        setCatalog(result);
        setSelectedKey(
          recommendedPackageKey(result, recommendationGapRef.current),
        );
      })
      .catch((catalogError: unknown) => {
        if (!active) return;
        setError(
          catalogError instanceof Error
            ? catalogError.message
            : t("creditPurchaseLoadError"),
        );
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [locale, t]);

  return {
    catalog,
    selectedKey,
    consentState,
    isLoading,
    error,
    setSelectedKey,
    setConsentState,
    setError,
  };
}

function moveFocusWithinDialog(
  event: KeyboardEvent,
  dialog: HTMLDivElement,
): void {
  const focusable = focusableElements(dialog);
  if (focusable.length === 0) {
    event.preventDefault();
    dialog.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const activeElement = document.activeElement;
  const focusIsInside =
    activeElement instanceof Node && dialog.contains(activeElement);
  if (event.shiftKey && (!focusIsInside || activeElement === first)) {
    event.preventDefault();
    last.focus();
    return;
  }
  if (!event.shiftKey && (!focusIsInside || activeElement === last)) {
    event.preventDefault();
    first.focus();
  }
}

function handleDialogKeyDown(
  event: KeyboardEvent,
  dialog: HTMLDivElement | null,
  close: () => void,
): void {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
    return;
  }
  if (event.key === "Tab" && dialog) moveFocusWithinDialog(event, dialog);
}

function useDialogFocus(
  close: () => void,
  dialogRef: React.RefObject<HTMLDivElement | null>,
  closeButtonRef: React.RefObject<HTMLButtonElement | null>,
): void {
  useEffect(() => {
    const previouslyFocused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const handleKeyDown = (event: KeyboardEvent) => {
      handleDialogKeyDown(event, dialogRef.current, close);
    };
    document.addEventListener("keydown", handleKeyDown);
    queueMicrotask(() => closeButtonRef.current?.focus());
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      queueMicrotask(() => {
        if (previouslyFocused?.isConnected) previouslyFocused.focus();
      });
    };
  }, [close, closeButtonRef, dialogRef]);
}

function disclosureIsReady(
  catalog: CreditCatalogResponse | null,
  contract: ConsumerContract | null,
  locale: string,
): boolean {
  return Boolean(
    catalog &&
    Array.isArray(catalog.billing_country_scope) &&
    catalog.billing_country_scope.length === 1 &&
    catalog.billing_country_scope[0] === "GR" &&
    catalog.consumer_contract_status === "approved" &&
    contract?.status === "approved" &&
    contract.locale === locale &&
    paidCreditLegalPublicationIsApproved(),
  );
}

function reviewModeEnabled(
  catalog: CreditCatalogResponse | null,
  disclosureReady: boolean,
): boolean {
  return Boolean(
    !catalog?.checkout_enabled &&
    disclosureReady &&
    process.env.NEXT_PUBLIC_PAID_CREDITS_UI_REVIEW === "1",
  );
}

function findSelectedPackage(
  catalog: CreditCatalogResponse | null,
  selectedKey: string,
): CreditPackage | null {
  return catalog?.packages.find((item) => item.key === selectedKey) ?? null;
}

function paidSalesState(
  catalog: CreditCatalogResponse | null,
  contract: ConsumerContract | null,
  locale: I18nValue["locale"],
) {
  const disclosureReady = disclosureIsReady(catalog, contract, locale);
  const available = Boolean(catalog?.checkout_enabled && disclosureReady);
  return {
    available,
    visible: available || reviewModeEnabled(catalog, disclosureReady),
  };
}

function contractConsentState(
  contract: ConsumerContract | null,
  consentState: ContractConsentState | null,
) {
  const disclosureIdentity = contract
    ? contractDisclosureIdentity(contract)
    : null;
  const consentMatches =
    disclosureIdentity !== null &&
    consentState?.disclosureIdentity === disclosureIdentity;
  return {
    disclosureIdentity,
    combinedConsentAccepted: Boolean(
      consentMatches && consentState?.combinedAccepted,
    ),
    termsBaseUrl: contract ? contract.terms_url.split("#")[0] : "/terms",
  };
}

function derivePurchaseState(
  catalog: CreditCatalogResponse | null,
  selectedKey: string,
  consentState: ContractConsentState | null,
  locale: I18nValue["locale"],
): PurchaseDerivedState {
  const selectedPackage = findSelectedPackage(catalog, selectedKey);
  const consumerContract = catalog?.consumer_contract ?? null;
  const paidSales = paidSalesState(catalog, consumerContract, locale);
  const consent = contractConsentState(consumerContract, consentState);
  return {
    selectedPackage,
    consumerContract,
    paidSalesAvailable: paidSales.available,
    paidSalesVisible: paidSales.visible,
    ...consent,
  };
}

function checkoutCanStart(
  selectedPackage: CreditPackage | null,
  catalog: CreditCatalogResponse | null,
  contract: ConsumerContract | null,
  paidSalesAvailable: boolean,
  disclosureIdentity: string | null,
  consentState: ContractConsentState | null,
  combinedConsentAccepted: boolean,
): boolean {
  return Boolean(
    selectedPackage &&
    catalog &&
    contract &&
    paidSalesAvailable &&
    disclosureIdentity &&
    consentState?.disclosureIdentity === disclosureIdentity &&
    combinedConsentAccepted,
  );
}

function checkoutConsent(contract: ConsumerContract) {
  return {
    disclosure_id: contract.disclosure_id,
    disclosure_sha256: contract.disclosure_sha256,
    locale: contract.locale,
    policy_version: contract.policy_version,
    terms_version: contract.terms_version,
    withdrawal_notice_version: contract.withdrawal_notice_version,
    terms_accepted: true as const,
    immediate_performance_requested: true as const,
    withdrawal_consequences_acknowledged: true as const,
  };
}

function useCheckoutAction({
  isAuthenticated,
  onRequireAuth,
  onRedirect,
  selectedPackage,
  catalog,
  consumerContract,
  paidSalesAvailable,
  disclosureIdentity,
  consentState,
  combinedConsentAccepted,
  idempotencyKeyRef,
  setError,
  t,
}: {
  isAuthenticated: boolean;
  onRequireAuth: () => void;
  onRedirect: (checkoutUrl: string) => void;
  selectedPackage: CreditPackage | null;
  catalog: CreditCatalogResponse | null;
  consumerContract: ConsumerContract | null;
  paidSalesAvailable: boolean;
  disclosureIdentity: string | null;
  consentState: ContractConsentState | null;
  combinedConsentAccepted: boolean;
  idempotencyKeyRef: React.MutableRefObject<string>;
  setError: (error: string) => void;
  t: Translate;
}) {
  const [isCheckingOut, setIsCheckingOut] = useState(false);
  const handleCheckout = useCallback(async () => {
    if (!isAuthenticated) {
      onRequireAuth();
      return;
    }
    if (
      !checkoutCanStart(
        selectedPackage,
        catalog,
        consumerContract,
        paidSalesAvailable,
        disclosureIdentity,
        consentState,
        combinedConsentAccepted,
      )
    ) {
      return;
    }
    if (!selectedPackage || !catalog || !consumerContract) return;
    setIsCheckingOut(true);
    setError("");
    try {
      const result = await api.createCreditCheckout(
        selectedPackage.key,
        idempotencyKeyRef.current,
        catalog.catalog_version,
        "GR",
        checkoutConsent(consumerContract),
      );
      if (
        !result.checkout_url ||
        !isAllowedStripeCheckoutUrl(result.checkout_url)
      ) {
        throw new Error(t("creditPurchaseUnsafeRedirect"));
      }
      onRedirect(result.checkout_url);
    } catch (checkoutError) {
      setError(
        checkoutError instanceof Error
          ? checkoutError.message
          : t("creditPurchaseError"),
      );
      setIsCheckingOut(false);
    }
  }, [
    catalog,
    combinedConsentAccepted,
    consentState,
    consumerContract,
    disclosureIdentity,
    idempotencyKeyRef,
    isAuthenticated,
    onRedirect,
    onRequireAuth,
    paidSalesAvailable,
    selectedPackage,
    setError,
    t,
  ]);
  return { isCheckingOut, handleCheckout };
}

function useDialogClose(
  onClose: () => void,
  dialogRef: React.RefObject<HTMLDivElement | null>,
  closeButtonRef: React.RefObject<HTMLButtonElement | null>,
): () => void {
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  const close = useCallback(() => onCloseRef.current(), []);
  useDialogFocus(close, dialogRef, closeButtonRef);
  return close;
}

function usePackageInteractions(
  state: CatalogState,
  disclosureIdentity: string | null,
  idempotencyKeyRef: React.MutableRefObject<string>,
): PackageInteractions {
  const packageRadioRefs = useRef(new Map<string, HTMLInputElement>());
  const changePackage = useCallback(
    (packageKey: string) => {
      state.setSelectedKey(packageKey);
      state.setError("");
      state.setConsentState(null);
      idempotencyKeyRef.current = checkoutIdempotencyKey();
    },
    [idempotencyKeyRef, state],
  );
  const updateConsent = useCallback(
    (checked: boolean) => {
      if (!disclosureIdentity) return;
      state.setConsentState({ disclosureIdentity, combinedAccepted: checked });
    },
    [disclosureIdentity, state],
  );
  const handlePackageKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>, packageIndex: number) => {
      const packages = state.catalog?.packages ?? [];
      if (packages.length === 0) return;
      const nextIndex = packageIndexForKey(
        event.key,
        packageIndex,
        packages.length,
      );
      if (nextIndex === null) return;
      event.preventDefault();
      const nextPackage = packages[nextIndex];
      changePackage(nextPackage.key);
      queueMicrotask(() =>
        packageRadioRefs.current.get(nextPackage.key)?.focus(),
      );
    },
    [changePackage, state.catalog],
  );
  const registerPackageRadio = useCallback(
    (packageKey: string, element: HTMLInputElement | null) => {
      if (element) packageRadioRefs.current.set(packageKey, element);
      else packageRadioRefs.current.delete(packageKey);
    },
    [],
  );
  return {
    changePackage,
    updateConsent,
    handlePackageKeyDown,
    registerPackageRadio,
  };
}

function buildController({
  wallet,
  state,
  derived,
  interactions,
  checkout,
  missingCredits,
  ids,
  close,
}: {
  wallet: ReturnType<typeof usePoints>;
  state: CatalogState;
  derived: PurchaseDerivedState;
  interactions: PackageInteractions;
  checkout: ReturnType<typeof useCheckoutAction>;
  missingCredits: number;
  ids: { combinedConsentId: string; consentConsequenceId: string };
  close: () => void;
}): CreditPurchaseController {
  return {
    aiSpendableBalance: wallet.aiSpendableBalance,
    reversalDebt: wallet.reversalDebt,
    catalog: state.catalog,
    selectedPackage: derived.selectedPackage,
    selectedKey: state.selectedKey,
    consumerContract: derived.consumerContract,
    paidSalesVisible: derived.paidSalesVisible,
    combinedConsentAccepted: derived.combinedConsentAccepted,
    paidCreditsTermsUrl: `${derived.termsBaseUrl}#seller`,
    withdrawalRightsUrl: `${derived.termsBaseUrl}#withdrawal-rights`,
    missingCredits,
    isLoading: state.isLoading,
    isCheckingOut: checkout.isCheckingOut,
    error: state.error,
    ...ids,
    close,
    ...interactions,
    handleCheckout: checkout.handleCheckout,
  };
}

function useConfiguredCheckout(
  options: Pick<
    Required<OpenCreditPurchaseDialogProps>,
    "isAuthenticated" | "onRequireAuth" | "onRedirect" | "t"
  >,
  state: CatalogState,
  derived: PurchaseDerivedState,
  idempotencyKeyRef: React.MutableRefObject<string>,
) {
  return useCheckoutAction({
    ...options,
    selectedPackage: derived.selectedPackage,
    catalog: state.catalog,
    consumerContract: derived.consumerContract,
    paidSalesAvailable: derived.paidSalesAvailable,
    disclosureIdentity: derived.disclosureIdentity,
    consentState: state.consentState,
    combinedConsentAccepted: derived.combinedConsentAccepted,
    idempotencyKeyRef,
    setError: state.setError,
  });
}

function useConsentIds() {
  return {
    combinedConsentId: useId(),
    consentConsequenceId: useId(),
  };
}

export function useCreditPurchaseController({
  isAuthenticated,
  requiredCredits,
  onClose,
  onRequireAuth,
  locale,
  t,
  onRedirect,
  dialogRef,
  closeButtonRef,
}: Required<OpenCreditPurchaseDialogProps> & {
  dialogRef: React.RefObject<HTMLDivElement | null>;
  closeButtonRef: React.RefObject<HTMLButtonElement | null>;
}): CreditPurchaseController {
  const wallet = usePoints();
  const missingCredits = creditGap(requiredCredits, wallet.aiSpendableBalance);
  const state = useCreditCatalog(locale, t, missingCredits);
  const derived = derivePurchaseState(
    state.catalog,
    state.selectedKey,
    state.consentState,
    locale,
  );
  const idempotencyKeyRef = useRef(checkoutIdempotencyKey());
  const interactions = usePackageInteractions(
    state,
    derived.disclosureIdentity,
    idempotencyKeyRef,
  );
  const close = useDialogClose(onClose, dialogRef, closeButtonRef);
  const checkout = useConfiguredCheckout(
    { isAuthenticated, onRequireAuth, onRedirect, t },
    state,
    derived,
    idempotencyKeyRef,
  );
  useDocumentScrollLock(true);
  const ids = useConsentIds();
  return buildController({
    wallet,
    state,
    derived,
    interactions,
    checkout,
    missingCredits,
    ids,
    close,
  });
}
