'use client';

import { useAppEnv } from '@/context/AppEnvContext';

export function AppEnvBadge() {
  const { appEnv } = useAppEnv();
  const label = appEnv === 'dev' ? 'DEV' : 'PROD';

  return (
    <div
      data-testid="app-env-badge"
      className="fixed bottom-4 left-4 z-30 inline-flex items-center gap-2 rounded-full border border-[var(--border)]/70 bg-[var(--surface-elevated)]/85 px-3 py-1 text-[10px] font-semibold tracking-[0.26em] text-[var(--muted)] backdrop-blur"
      aria-label={`Environment: ${label}`}
      title={`Environment: ${label}`}
    >
      <span
        aria-hidden="true"
        className="h-2 w-2 rounded-full bg-[var(--accent)] shadow-[0_0_0_3px_rgb(var(--accent-rgb)_/_0.22)]"
      />
      <span>{label}</span>
    </div>
  );
}

