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
  onOpenHistory: () => void;
}

interface DashboardAccountControlsProps extends Omit<
  DashboardHeaderProps,
  "isInert" | "onBrandHomeClick" | "onOpenHistory"
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

function DashboardHistoryButton(
  props: Pick<
    DashboardHeaderProps,
    "user" | "accountReturnFocusRef" | "onOpenHistory"
  >,
) {
  const { t } = useI18n();
  if (!props.user) return null;
  return (
    <button
      type="button"
      className="studio-history-trigger"
      aria-label={t("myVideos")}
      aria-haspopup="dialog"
      onClick={(event) => {
        props.accountReturnFocusRef.current = event.currentTarget;
        props.onOpenHistory();
      }}
    >
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect
          x="3"
          y="6"
          width="18"
          height="15"
          rx="3"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        <path
          d="M7 3h10M10 10l5 3.5-5 3.5v-7Z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>{t("myVideos")}</span>
    </button>
  );
}

export function DashboardHeader(props: DashboardHeaderProps) {
  const { t } = useI18n();
  return (
    <header
      className="studio-header"
      aria-label="gsubs studio"
      aria-hidden={props.isInert || undefined}
      inert={props.isInert ? true : undefined}
    >
      <a className="studio-skip-link" href="#studio-content">
        {t("skipToContent")}
      </a>
      <Link
        href="/"
        className="studio-brand"
        aria-label={t("brandHomeLabel")}
        onClick={props.onBrandHomeClick}
      >
        <BetaBrandLogo className="block h-auto w-[68px] sm:w-[72px]" />
      </Link>
      <div className="studio-header-account">
        <DashboardHistoryButton {...props} />
        <LanguageToggle />
        <DashboardAccountControls
          {...props}
          guestSignInLabel={t("guestSignIn")}
          profileLabel={t("profileLabel")}
          accountSettingsTitle={t("accountSettingsTitle")}
        />
      </div>
    </header>
  );
}
