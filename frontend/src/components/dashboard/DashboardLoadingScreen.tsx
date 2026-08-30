"use client";

import { BrandLogo } from "@/components/BrandLogo";
import { useI18n } from "@/context/I18nContext";

export function DashboardLoadingScreen() {
  const { t } = useI18n();
  return (
    <div
      className="studio-loading-screen"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="studio-loading-content">
        <BrandLogo className="studio-loading-logo block h-auto" />
        <div className="studio-loading-wave" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
        <p>{t("loading")}</p>
      </div>
    </div>
  );
}
