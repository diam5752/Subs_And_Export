"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BrandLogo } from "@/components/BrandLogo";
import { Spinner } from "@/components/Spinner";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import {
  fetchObservabilitySnapshot,
  type ObservabilitySnapshot,
} from "@/lib/observability";

const REFRESH_INTERVAL_MS = 15_000;
type Translate = ReturnType<typeof useI18n>["t"];
type DashboardStateProps = ReturnType<typeof useSnapshot> & {
  authLoading: boolean;
  hasUser: boolean;
  locale: string;
  t: Translate;
};

function useSnapshot(active: boolean, authLoading: boolean) {
  const [snapshot, setSnapshot] = useState<ObservabilitySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const refresh = useCallback(async () => {
    if (!active) {
      setLoading(false);
      return;
    }
    try {
      setSnapshot(await fetchObservabilitySnapshot());
      setAccessDenied(false);
      setLoadError(false);
    } catch (error) {
      const denied = error instanceof Error && error.message.endsWith("_403");
      setAccessDenied(denied);
      setLoadError(!denied);
    } finally {
      setLoading(false);
    }
  }, [active]);
  useEffect(() => {
    if (authLoading) return;
    queueMicrotask(() => void refresh());
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [authLoading, refresh]);
  return { snapshot, loading, accessDenied, loadError, refresh };
}

function ActiveCards({
  snapshot,
  t,
}: {
  snapshot: ObservabilitySnapshot;
  t: Translate;
}) {
  const errors = ["frontend_error", "api_error", "backend_error"].reduce(
    (total, key) => total + (snapshot.totals[key] ?? 0),
    0,
  );
  const cards = [
    [t("observabilityLiveTotal"), snapshot.active.estimated_total],
    [t("observabilityLiveAccounts"), snapshot.active.authenticated_accounts],
    [t("observabilityLiveGuests"), snapshot.active.guest_browser_sessions],
    [t("observabilityErrors"), errors],
  ];
  return (
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(([label, value]) => (
        <article
          key={String(label)}
          className="rounded-2xl border border-[var(--border)] bg-white p-5"
        >
          <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--muted)]">
            {label}
          </p>
          <p className="mt-3 text-4xl font-extrabold tabular-nums">{value}</p>
        </article>
      ))}
    </section>
  );
}

function JobStates({
  snapshot,
  t,
}: {
  snapshot: ObservabilitySnapshot;
  t: Translate;
}) {
  return (
    <section>
      <h2 className="text-2xl font-bold">{t("observabilityJobsTitle")}</h2>
      <div className="mt-4 flex flex-wrap gap-2">
        {Object.entries(snapshot.jobs).map(([status, value]) => (
          <span
            key={status}
            className="rounded-full border border-[var(--border)] bg-white px-4 py-2 text-sm"
          >
            <strong>{status}</strong> · {value}
          </span>
        ))}
      </div>
    </section>
  );
}

function CountList({
  title,
  items,
}: {
  title: string;
  items: Array<{ key: string; label: string; count: number }>;
}) {
  return (
    <div>
      <h2 className="text-2xl font-bold">{title}</h2>
      <div className="mt-4 overflow-hidden rounded-2xl border border-[var(--border)] bg-white">
        {items.map((item) => (
          <div
            key={item.key}
            className="flex justify-between gap-4 border-b border-[var(--border)] px-4 py-3 last:border-0"
          >
            <code className="text-xs">{item.label}</code>
            <strong className="tabular-nums">{item.count}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function DiagnosticCounts({
  snapshot,
  t,
}: {
  snapshot: ObservabilitySnapshot;
  t: Translate;
}) {
  const actions = snapshot.actions.map((item) => ({
    key: `${item.name}-${item.outcome}-${item.export_format}`,
    label: `${item.name} · ${item.outcome}${item.export_format ? ` · ${item.export_format}` : ""}`,
    count: item.count,
  }));
  const errors = snapshot.errors.map((item) => ({
    key: `${item.kind}-${item.name}-${item.route}-${item.status_code}`,
    label: `${item.kind} · ${item.name} · ${item.route}${item.status_code ? ` · ${item.status_code}` : ""}`,
    count: item.count,
  }));
  return (
    <section className="grid gap-8 lg:grid-cols-2">
      <CountList title={t("observabilityActionsTitle")} items={actions} />
      <CountList title={t("observabilityErrorsTitle")} items={errors} />
    </section>
  );
}

function RecentEvents({
  snapshot,
  locale,
  t,
}: {
  snapshot: ObservabilitySnapshot;
  locale: string;
  t: Translate;
}) {
  const formatTime = (timestamp: number) =>
    new Intl.DateTimeFormat(locale, {
      dateStyle: "short",
      timeStyle: "medium",
    }).format(new Date(timestamp * 1_000));
  return (
    <section>
      <h2 className="text-2xl font-bold">{t("observabilityRecentTitle")}</h2>
      <div className="mt-4 overflow-x-auto rounded-2xl border border-[var(--border)] bg-white">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-[#f1f1ef] text-xs uppercase tracking-[0.1em] text-[var(--muted)]">
            <tr>
              <th className="p-3">{t("observabilityTime")}</th>
              <th className="p-3">Event</th>
              <th className="p-3">Route</th>
              <th className="p-3">State</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.recent.map((item, index) => (
              <tr
                key={`${item.ts}-${item.kind}-${item.name}-${index}`}
                className="border-t border-[var(--border)]"
              >
                <td className="p-3 whitespace-nowrap">{formatTime(item.ts)}</td>
                <td className="p-3">
                  <code>
                    {item.kind} · {item.name}
                  </code>
                </td>
                <td className="p-3">
                  <code>{item.route}</code>
                </td>
                <td className="p-3">
                  <code>{item.auth_state}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-[var(--muted)]">
        {t("observabilityWindow", {
          hours: snapshot.retention_hours,
          seconds: snapshot.active.window_seconds,
        })}
      </p>
    </section>
  );
}

function SnapshotDashboard({
  snapshot,
  locale,
  t,
}: {
  snapshot: ObservabilitySnapshot;
  locale: string;
  t: Translate;
}) {
  return (
    <div className="mt-10 space-y-10">
      <ActiveCards snapshot={snapshot} t={t} />
      <JobStates snapshot={snapshot} t={t} />
      <DiagnosticCounts snapshot={snapshot} t={t} />
      <RecentEvents snapshot={snapshot} locale={locale} t={t} />
    </div>
  );
}

function DashboardState(props: DashboardStateProps) {
  if (props.authLoading || props.loading)
    return (
      <div className="grid min-h-64 place-items-center">
        <span className="flex items-center gap-3 font-semibold text-[var(--muted)]">
          <Spinner className="h-5 w-5" /> {props.t("observabilityLoading")}
        </span>
      </div>
    );
  if (!props.hasUser)
    return (
      <Link
        href="/login"
        className="mt-8 inline-flex font-bold text-[var(--accent)] underline"
      >
        {props.t("observabilitySignIn")}
      </Link>
    );
  if (props.accessDenied)
    return (
      <p
        role="alert"
        className="mt-8 rounded-xl border border-red-300 bg-red-50 p-5 text-red-900"
      >
        {props.t("observabilityForbidden")}
      </p>
    );
  if (props.loadError || !props.snapshot)
    return (
      <button
        type="button"
        onClick={() => void props.refresh()}
        className="mt-8 min-h-11 rounded-xl border border-red-400 px-4 font-bold text-red-900"
      >
        {props.t("observabilityRetry")}
      </button>
    );
  return (
    <SnapshotDashboard
      snapshot={props.snapshot}
      locale={props.locale}
      t={props.t}
    />
  );
}

export default function ObservabilityAdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const { locale, t } = useI18n();
  const state = useSnapshot(Boolean(user), authLoading);
  return (
    <div className="min-h-dvh bg-[#f7f7f5] text-[var(--foreground)]">
      <header className="border-b border-[#deded9]">
        <div className="mx-auto flex min-h-[72px] max-w-6xl items-center justify-between px-5 sm:px-8">
          <Link href="/" aria-label={t("brandHomeLabel")}>
            <BrandLogo className="block h-auto w-[72px]" />
          </Link>
          <Link href="/" className="text-sm font-semibold text-[var(--muted)]">
            {t("observabilityBack")}
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 sm:py-14">
        <p className="text-xs font-extrabold tracking-[0.18em] text-[var(--accent)]">
          {t("observabilityKicker")}
        </p>
        <h1 className="mt-3 text-4xl font-extrabold tracking-[-0.045em] sm:text-6xl">
          {t("observabilityTitle")}
        </h1>
        <p className="mt-4 max-w-3xl leading-7 text-[var(--muted)]">
          {t("observabilityDescription")}
        </p>
        <p className="mt-4 max-w-3xl rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm leading-6 text-sky-950">
          {t("observabilityPrivacy")}
        </p>
        <DashboardState
          {...state}
          authLoading={authLoading}
          hasUser={Boolean(user)}
          locale={locale}
          t={t}
        />
      </main>
    </div>
  );
}
