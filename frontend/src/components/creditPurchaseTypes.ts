import type { useI18n } from "@/context/I18nContext";
import type { CreditCatalogResponse } from "@/lib/api";

export interface CreditPurchaseDialogProps {
  isOpen: boolean;
  isAuthenticated: boolean;
  requiredCredits?: number;
  onClose: () => void;
  onRequireAuth: () => void;
  onRedirect?: (checkoutUrl: string) => void;
}

export type I18nValue = ReturnType<typeof useI18n>;
export type Translate = I18nValue["t"];
export type ConsumerContract = NonNullable<
  CreditCatalogResponse["consumer_contract"]
>;

export interface OpenCreditPurchaseDialogProps extends Omit<
  CreditPurchaseDialogProps,
  "isOpen"
> {
  locale: I18nValue["locale"];
  t: Translate;
}

export interface ContractConsentState {
  disclosureIdentity: string;
  combinedAccepted: boolean;
}
