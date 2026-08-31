"use client";

import { useI18n } from "@/context/I18nContext";

export function BetaLaunchCreditAward({
  count,
  onDismiss,
}: {
  count: number;
  onDismiss: () => void;
}) {
  const { t } = useI18n();

  return (
    <div
      role="status"
      data-testid="beta-launch-credit-award"
      className="mb-5 flex items-center justify-between gap-4 rounded-2xl border border-sky-300 bg-sky-50 px-4 py-3 text-sky-950 shadow-[0_12px_28px_rgba(14,165,233,0.08)]"
    >
      <div className="min-w-0">
        <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-sky-600">
          {t("betaLaunchOfferKicker")}
        </p>
        <p className="mt-1 text-sm font-bold">
          {t("betaLaunchAwardTitle", { count })}
        </p>
        <p className="mt-0.5 text-xs text-sky-800">
          {t("betaLaunchAwardBody")}
        </p>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-sky-700 hover:bg-sky-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
        aria-label={t("betaLaunchAwardDismiss")}
      >
        ✕
      </button>
    </div>
  );
}
