"use client";

import { lazy, Suspense, useRef, useState } from "react";
import { useI18n } from "@/context/I18nContext";

const LazyFeedbackWidget = lazy(async () => {
  const feedbackModule = await import("@/components/FeedbackWidget");
  return { default: feedbackModule.FeedbackWidget };
});

function FeedbackTrigger({
  expanded,
  busy = false,
  onClick,
}: {
  expanded: boolean;
  busy?: boolean;
  onClick?: () => void;
}) {
  const { t } = useI18n();
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <button
      ref={triggerRef}
      type="button"
      aria-label={t("feedbackOpen")}
      aria-expanded={expanded}
      aria-controls="gsubs-feedback-dialog"
      aria-busy={busy || undefined}
      onClick={onClick}
      data-testid="feedback-trigger"
      className="fixed bottom-[calc(env(safe-area-inset-bottom)_+_1rem)] right-[calc(env(safe-area-inset-right)_+_1rem)] z-40 inline-flex min-h-12 items-center gap-2 rounded-full border border-[#d7d9de] bg-white px-3.5 py-2.5 text-sm font-bold text-[#24272d] shadow-[0_12px_32px_rgb(20_24_32/0.16)] transition duration-150 hover:-translate-y-0.5 hover:border-[#b9bdc5] hover:shadow-[0_16px_38px_rgb(20_24_32/0.2)] sm:px-4"
    >
      <svg
        className="h-5 w-5 text-[var(--accent)]"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.9"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M7.5 18.5 4 20l1.15-3.8A8 8 0 1 1 7.5 18.5Z"
        />
        <path strokeLinecap="round" d="M8.5 9.5h7M8.5 13h4.5" />
      </svg>
      <span className="hidden sm:inline">{t("feedbackOpenShort")}</span>
    </button>
  );
}

/** Keep the form, auth lookup, API client and react-hook-form off the critical path. */
export function FeedbackWidgetLauncher() {
  const [activated, setActivated] = useState(false);

  if (!activated) {
    return (
      <FeedbackTrigger expanded={false} onClick={() => setActivated(true)} />
    );
  }

  return (
    <Suspense fallback={<FeedbackTrigger expanded busy />}>
      <LazyFeedbackWidget initiallyOpen />
    </Suspense>
  );
}
