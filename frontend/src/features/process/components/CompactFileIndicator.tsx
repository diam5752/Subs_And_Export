import Image from "next/image";
import type { useI18n } from "@/context/I18nContext";

type Translate = ReturnType<typeof useI18n>["t"];

interface CompactFileIndicatorProps {
  isExpanded: boolean;
  hasVideo: boolean;
  thumbnailUrl?: string | null;
  fileName: string;
  t: Translate;
}

function CompactFileVisual({
  thumbnailUrl,
  t,
}: Pick<CompactFileIndicatorProps, "thumbnailUrl" | "t">) {
  if (thumbnailUrl) {
    return (
      <div className="relative w-5 h-5 rounded-full overflow-hidden flex-shrink-0">
        <Image
          src={thumbnailUrl}
          alt={t("videoThumbnailAlt")}
          fill
          unoptimized
          className="object-cover"
          sizes="20px"
        />
      </div>
    );
  }
  return (
    <svg
      className="w-4 h-4 text-emerald-500 flex-shrink-0"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M5 13l4 4L19 7"
      />
    </svg>
  );
}

export function CompactFileIndicator(props: CompactFileIndicatorProps) {
  if (props.isExpanded || !props.hasVideo) return null;
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--surface-elevated)] border border-[var(--border)] overflow-hidden">
      <CompactFileVisual thumbnailUrl={props.thumbnailUrl} t={props.t} />
      <span className="text-sm font-medium text-[var(--foreground)] truncate max-w-[120px]">
        {props.fileName}
      </span>
    </div>
  );
}
