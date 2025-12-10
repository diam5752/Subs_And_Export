import { API_BASE } from './api';

/**
 * Format a timestamp into a locale string.
 * Returns the original value as string if parsing fails.
 */
export function formatDate(ts: string | number): string {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts.toString();
    return d.toLocaleString();
}

/**
 * Build a static URL for serving files from the API.
 * Handles various path formats and ensures proper /static/ prefix.
 */
export function buildStaticUrl(path?: string | null): string | null {
    if (!path) return null;
    const cleaned = path.replace(/^https?:\/\/[^/]+/i, '');
    const withPrefix = cleaned.startsWith('/static/')
        ? cleaned
        : `/static/${cleaned.replace(/^\/?data\//, '').replace(/^\/?static\//, '')}`;
    return `${API_BASE}${withPrefix}`;
}
