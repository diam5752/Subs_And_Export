"use client";

import Link from "next/link";
import type { MouseEvent, RefObject } from "react";
import { BetaBrandLogo } from "@/components/BetaBrandLogo";
import { CreditsBadge } from "@/components/CreditsBadge";
import { LanguageToggle } from "@/components/LanguageToggle";
import { ProfileAvatar } from "@/components/ProfileAvatar";
import type { User } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";

interface DashboardHeaderProps {
  user: User | null;
  isInert: boolean;
  paidCreditSalesUiApproved: boolean;
  accountPanelOpen: boolean;
  accountReturnFocusRef: RefObject<HTMLElement | null>;
  onBrandHomeClick: (event: MouseEvent<HTMLAnchorElement>) => void;
  onOpenCreditPurchase: () => void;
  onOpenAccount: () => void;
}

interface DashboardAccountControlsProps extends Omit<
  DashboardHeaderProps,
  "isInert" | "onBrandHomeClick"
> {
  guestSignInLabel: string;
  profileLabel: string;
  accountSettingsTitle: string;
}

function DashboardAccountControls({
  user,
  paidCreditSalesUiApproved,
  accountPanelOpen,
  accountReturnFocusRef,
  onOpenCreditPurchase,
  onOpenAccount,
  guestSignInLabel,
  profileLabel,
  accountSettingsTitle,
}: DashboardAccountControlsProps) {
  if (!user) {
    return (
      <Link
        href="/login"
        className="guest-sign-in inline-flex min-h-10 items-center justify-center rounded-full border border-[var(--border-strong)] bg-white px-4 text-sm font-semibold text-[var(--foreground)] transition-colors hover:bg-[#f5f5f4]"
      >
        {guestSignInLabel}
      </Link>
    );
  }
  return (
    <>
      <div
        className="studio-header-credits"
        data-testid="studio-header-credits"
      >
        <CreditsBadge
          onClick={paidCreditSalesUiApproved ? onOpenCreditPurchase : undefined}
        />
      </div>
      <button
        onClick={() => {
          accountReturnFocusRef.current =
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null;
          onOpenAccount();
        }}
        className="profile-trigger"
        aria-expanded={accountPanelOpen}
        aria-label={profileLabel}
        title={accountSettingsTitle}
      >
        <ProfileAvatar name={user.name} avatarUrl={user.avatar_url} />
      </button>
    </>
  );
}

export function DashboardHeader({
  user,
  isInert,
  paidCreditSalesUiApproved,
  accountPanelOpen,
  accountReturnFocusRef,
  onBrandHomeClick,
  onOpenCreditPurchase,
  onOpenAccount,
}: DashboardHeaderProps) {
  const { t } = useI18n();

  return (
    <header
      className="studio-header"
      aria-label="gsubs studio"
      aria-hidden={isInert || undefined}
      inert={isInert ? true : undefined}
    >
      <Link
        href="/"
        className="studio-brand"
        aria-label={t("brandHomeLabel")}
        onClick={onBrandHomeClick}
      >
        <BetaBrandLogo className="block h-auto w-[68px] sm:w-[72px]" />
      </Link>

      <div className="studio-header-account">
        <LanguageToggle />
        <DashboardAccountControls
          user={user}
          paidCreditSalesUiApproved={paidCreditSalesUiApproved}
          accountPanelOpen={accountPanelOpen}
          accountReturnFocusRef={accountReturnFocusRef}
          onOpenCreditPurchase={onOpenCreditPurchase}
          onOpenAccount={onOpenAccount}
          guestSignInLabel={t("guestSignIn")}
          profileLabel={t("profileLabel")}
          accountSettingsTitle={t("accountSettingsTitle")}
        />
      </div>
    </header>
  );
}
