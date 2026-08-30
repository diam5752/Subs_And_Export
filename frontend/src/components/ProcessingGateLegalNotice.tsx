import Link from "next/link";
import type { useI18n } from "@/context/I18nContext";

type Translate = ReturnType<typeof useI18n>["t"];

export function ProcessingGateLegalNotice({ t }: { t: Translate }) {
  return (
    <p
      id="processing-gate-register-legal-notice"
      className="text-xs leading-5 text-[var(--muted)]"
    >
      {t("registerLegalIntro")}{" "}
      <Link
        href="/terms"
        target="_blank"
        rel="noopener noreferrer"
        className="rounded-sm font-semibold text-[var(--accent)] underline underline-offset-2 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2"
      >
        {t("registerLegalTermsLink")}
      </Link>{" "}
      {t("registerLegalConnector")}{" "}
      <Link
        href="/privacy"
        target="_blank"
        rel="noopener noreferrer"
        className="rounded-sm font-semibold text-[var(--accent)] underline underline-offset-2 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2"
      >
        {t("registerLegalPrivacyLink")}
      </Link>
      .
    </p>
  );
}
