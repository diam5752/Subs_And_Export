"use client";

import { useRef } from "react";
import { useI18n } from "@/context/I18nContext";
import { CreditPurchaseDialogView } from "./CreditPurchaseDialogView";
import { isAllowedStripeCheckoutUrl } from "./creditPurchaseSupport";
import type {
  CreditPurchaseDialogProps,
  OpenCreditPurchaseDialogProps,
} from "./creditPurchaseTypes";
import { useCreditPurchaseController } from "./useCreditPurchaseController";

export { isAllowedStripeCheckoutUrl };

export function CreditPurchaseDialog(props: CreditPurchaseDialogProps) {
  const { locale, t } = useI18n();
  const { isOpen, ...openProps } = props;
  if (!isOpen) return null;
  return (
    <OpenCreditPurchaseDialog
      key={locale}
      {...openProps}
      locale={locale}
      t={t}
    />
  );
}

function OpenCreditPurchaseDialog({
  isAuthenticated,
  requiredCredits = 0,
  onClose,
  onRequireAuth,
  locale,
  t,
  onRedirect = (checkoutUrl) => window.location.assign(checkoutUrl),
}: OpenCreditPurchaseDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const controller = useCreditPurchaseController({
    isAuthenticated,
    requiredCredits,
    onClose,
    onRequireAuth,
    locale,
    t,
    onRedirect,
    dialogRef,
    closeButtonRef,
  });
  return (
    <CreditPurchaseDialogView
      controller={controller}
      dialogRef={dialogRef}
      closeButtonRef={closeButtonRef}
      isAuthenticated={isAuthenticated}
      requiredCredits={requiredCredits}
      t={t}
    />
  );
}
