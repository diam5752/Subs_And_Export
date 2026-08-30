"use client";

import { useCallback, useEffect, useRef, type RefObject } from "react";
import { AccountView } from "@/components/AccountView";
import type { User } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { useDocumentScrollLock } from "@/hooks/useDocumentScrollLock";
import type { JobResponse } from "@/lib/api";

interface AccountDialogProps {
  user: User;
  activeTab: "profile" | "history";
  returnFocusRef: RefObject<HTMLElement | null>;
  accountMessage: string;
  accountError: string;
  accountSaving: boolean;
  recentJobs: JobResponse[];
  jobsLoading: boolean;
  selectedJobId?: string;
  currentPage: number;
  totalPages: number;
  totalJobs: number;
  pageSize: number;
  onClose: () => void;
  onTabChange: (tab: "profile" | "history") => void;
  onSaveProfile: (
    name: string,
    password?: string,
    confirmPassword?: string,
  ) => Promise<void>;
  onLogout: () => Promise<void>;
  onJobSelect: (job: JobResponse | null) => void;
  onRefreshJobs: () => Promise<void>;
  formatDate: (timestamp: number | string) => string;
  buildStaticUrl: (path?: string | null) => string | null;
  setShowPreview: (show: boolean) => void;
  onNextPage: () => void;
  onPrevPage: () => void;
}

type Translate = ReturnType<typeof useI18n>["t"];

function focusableElements(dialog: HTMLDivElement): HTMLElement[] {
  return Array.from(
    dialog.querySelectorAll<HTMLElement>(
      "a[href], button:not([disabled]), input:not([disabled]), " +
        "select:not([disabled]), textarea:not([disabled]), " +
        '[tabindex]:not([tabindex="-1"])',
    ),
  ).filter(
    (element) =>
      element.getAttribute("aria-hidden") !== "true" &&
      element.getClientRects().length > 0,
  );
}

function trapDialogTab(event: KeyboardEvent, dialog: HTMLDivElement): void {
  const focusable = focusableElements(dialog);
  if (focusable.length === 0) {
    event.preventDefault();
    dialog.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const activeElement = document.activeElement;
  const outsideDialog = !dialog.contains(activeElement);
  if (event.shiftKey && (activeElement === first || outsideDialog)) {
    event.preventDefault();
    last.focus();
    return;
  }
  if (!event.shiftKey && (activeElement === last || outsideDialog)) {
    event.preventDefault();
    first.focus();
  }
}

function AccountDialogHeader({
  activeTab,
  closeButtonRef,
  onClose,
  onTabChange,
  t,
}: {
  activeTab: AccountDialogProps["activeTab"];
  closeButtonRef: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  onTabChange: AccountDialogProps["onTabChange"];
  t: Translate;
}) {
  return (
    <div className="flex items-center justify-between gap-1 p-4 border-b border-[var(--border)] sm:gap-3">
      <div className="flex min-w-0 flex-1 items-center gap-1 sm:gap-4">
        {(["profile", "history"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => onTabChange(tab)}
            className={`min-h-11 min-w-0 px-1 text-xs font-semibold border-b-2 transition-colors sm:text-sm ${activeTab === tab ? "border-[var(--accent)] text-[var(--accent)]" : "border-transparent text-[var(--muted)] hover:text-[var(--foreground)]"}`}
          >
            {t(tab === "profile" ? "accountSettingsTitle" : "historyTitle")}
          </button>
        ))}
      </div>
      <button
        ref={closeButtonRef}
        onClick={onClose}
        className="flex min-h-11 min-w-11 flex-none items-center justify-center rounded-lg transition-colors hover:bg-black/5"
        aria-label={t("closeLabel")}
      >
        <span aria-hidden="true">✕</span>
      </button>
    </div>
  );
}

function AccountDialogBody(props: AccountDialogProps) {
  return (
    <div className="p-4 overflow-y-auto">
      <AccountView
        user={props.user}
        onSaveProfile={props.onSaveProfile}
        onLogout={props.onLogout}
        accountMessage={props.accountMessage}
        accountError={props.accountError}
        accountSaving={props.accountSaving}
        activeTab={props.activeTab}
        recentJobs={props.recentJobs}
        jobsLoading={props.jobsLoading}
        onJobSelect={props.onJobSelect}
        selectedJobId={props.selectedJobId}
        onRefreshJobs={props.onRefreshJobs}
        formatDate={props.formatDate}
        buildStaticUrl={props.buildStaticUrl}
        setShowPreview={props.setShowPreview}
        currentPage={props.currentPage}
        totalPages={props.totalPages}
        onNextPage={props.onNextPage}
        onPrevPage={props.onPrevPage}
        totalJobs={props.totalJobs}
        pageSize={props.pageSize}
      />
    </div>
  );
}

export function AccountDialog(props: AccountDialogProps) {
  const { activeTab, onClose, returnFocusRef } = props;
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  useDocumentScrollLock(true);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "Tab" && dialogRef.current) {
        trapDialogTab(event, dialogRef.current);
      }
    },
    [onClose],
  );

  useEffect(() => {
    const returnTarget = returnFocusRef.current;
    document.addEventListener("keydown", handleKeyDown);
    queueMicrotask(() => closeButtonRef.current?.focus());
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      queueMicrotask(() => {
        if (returnTarget?.isConnected) returnTarget.focus();
      });
    };
  }, [handleKeyDown, returnFocusRef]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center px-4 pt-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] sm:items-start sm:pt-20">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        ref={dialogRef}
        className="relative z-10 w-full max-w-2xl animate-fade-in"
        role="dialog"
        aria-modal="true"
        aria-label={
          activeTab === "profile"
            ? t("accountSettingsTitle")
            : t("historyTitle")
        }
        tabIndex={-1}
      >
        <div className="bg-[var(--surface-elevated)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden max-h-[90dvh] sm:max-h-[85dvh] flex flex-col">
          <AccountDialogHeader
            activeTab={activeTab}
            closeButtonRef={closeButtonRef}
            onClose={onClose}
            onTabChange={props.onTabChange}
            t={t}
          />
          <AccountDialogBody {...props} />
        </div>
      </div>
    </div>
  );
}
