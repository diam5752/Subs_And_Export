import { TokenIcon } from "@/components/icons";
import { useI18n } from "@/context/I18nContext";
import {
  formatPoints,
  processVideoCostForSelection,
  VIDEO_CREDIT_BRACKETS,
  videoCreditQuoteForDuration,
} from "@/lib/points";

const parsedMaxVideoDurationSeconds = Number(
  process.env.NEXT_PUBLIC_MAX_VIDEO_DURATION_SECONDS ?? "180",
);
export const MAX_VIDEO_DURATION_SECONDS =
  Number.isFinite(parsedMaxVideoDurationSeconds) &&
  parsedMaxVideoDurationSeconds > 0
    ? Math.floor(parsedMaxVideoDurationSeconds)
    : 180;
export const MAX_VIDEO_DURATION_LABEL = `${Math.floor(MAX_VIDEO_DURATION_SECONDS / 60)}:${String(MAX_VIDEO_DURATION_SECONDS % 60).padStart(2, "0")}`;

function formatVideoDuration(durationSeconds: number): string {
  const roundedSeconds = Math.max(1, Math.ceil(durationSeconds));
  return `${Math.floor(roundedSeconds / 60)}:${String(roundedSeconds % 60).padStart(2, "0")}`;
}

type VideoCreditQuote = (typeof VIDEO_CREDIT_BRACKETS)[number];

function VideoCreditTier({
  quote,
  selectedQuoteKey,
}: {
  quote: VideoCreditQuote;
  selectedQuoteKey: VideoCreditQuote["key"];
}) {
  const { t } = useI18n();
  const isAvailable = quote.maxDurationSeconds <= MAX_VIDEO_DURATION_SECONDS;
  const isActive = isAvailable && quote.key === selectedQuoteKey;
  const stateClass = isActive
    ? "border-sky-400 bg-sky-400/10 text-[var(--foreground)] shadow-[0_0_0_1px_rgba(56,189,248,0.12)]"
    : isAvailable
      ? "border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--muted)]"
      : "border-dashed border-[var(--border)] bg-[var(--surface-elevated)]/55 text-[var(--muted)] opacity-70";

  return (
    <div
      data-active={isActive ? "true" : "false"}
      data-available={isAvailable ? "true" : "false"}
      aria-disabled={!isAvailable}
      className={`rounded-xl border px-2 py-3 text-center transition ${stateClass}`}
    >
      <span className="block text-[10px] font-semibold uppercase tracking-wide">
        {t("videoCreditPricingUpTo", {
          minutes: quote.maxDurationSeconds / 60,
        })}
      </span>
      <strong className="mt-1 block text-sm">
        {isAvailable
          ? `${formatPoints(quote.credits)} ${t("creditsLabel")}`
          : t("videoCreditPricingComingSoon")}
      </strong>
    </div>
  );
}

export function VideoCreditPricing({
  durationSeconds,
  selectedCost,
  selectedDurationAvailable,
  selectedQuoteKey,
}: {
  durationSeconds: number | null;
  selectedCost: number;
  selectedDurationAvailable: boolean;
  selectedQuoteKey: VideoCreditQuote["key"];
}) {
  const { t } = useI18n();
  const priceLabel = selectedDurationAvailable
    ? `${formatPoints(selectedCost)} ${t("creditsLabel")}`
    : t("videoCreditPricingComingSoon");

  return (
    <div
      data-testid="video-credit-pricing"
      className="rounded-2xl border border-sky-400/20 bg-sky-400/[0.045] p-4"
    >
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-sky-500">
            {t("videoCreditPricingKicker")}
          </p>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {durationSeconds
              ? t("videoCreditPricingDuration", {
                  duration: formatVideoDuration(durationSeconds),
                })
              : t("videoCreditPricingPending")}
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm font-bold text-sky-500">
          {selectedDurationAvailable && <TokenIcon className="h-4 w-4" />}
          <span>{priceLabel}</span>
        </div>
      </div>
      <div
        className="grid grid-cols-3 gap-2"
        aria-label={t("videoCreditPricingTiers")}
      >
        {VIDEO_CREDIT_BRACKETS.map((quote) => (
          <VideoCreditTier
            key={quote.key}
            quote={quote}
            selectedQuoteKey={selectedQuoteKey}
          />
        ))}
      </div>
    </div>
  );
}

export function resolveVideoCreditPricing(
  durationSeconds: number | null,
  provider: string | null | undefined,
  mode: string | null | undefined,
) {
  const selectedQuote =
    durationSeconds === null
      ? (VIDEO_CREDIT_BRACKETS.find(
          (quote) => quote.maxDurationSeconds >= MAX_VIDEO_DURATION_SECONDS,
        ) ?? VIDEO_CREDIT_BRACKETS[0])
      : videoCreditQuoteForDuration(durationSeconds);
  const selectedCost =
    durationSeconds === null
      ? selectedQuote.credits
      : processVideoCostForSelection(provider, mode, durationSeconds);
  return {
    selectedQuote,
    selectedCost,
    selectedDurationAvailable:
      durationSeconds === null || durationSeconds <= MAX_VIDEO_DURATION_SECONDS,
  };
}
