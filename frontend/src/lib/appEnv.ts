export type AppEnv = 'dev' | 'production';

const DEV_ALIASES = new Set(['dev', 'development', 'local', 'localhost']);
const PROD_ALIASES = new Set(['prod', 'production']);

export function normalizeAppEnv(raw?: string | null): AppEnv {
  if (!raw) return 'dev';
  const lowered = raw.trim().toLowerCase();
  if (DEV_ALIASES.has(lowered)) return 'dev';
  if (PROD_ALIASES.has(lowered)) return 'production';
  return 'production';
}

export function isDevEnv(env: AppEnv): boolean {
  return env === 'dev';
}

