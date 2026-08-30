type RouteBucket =
  | "studio"
  | "auth"
  | "account"
  | "billing"
  | "feedback"
  | "observability"
  | "legal"
  | "other";
type ViewportBucket = "compact" | "regular" | "wide";
type ExportFormat = "720p" | "1080p" | "4k" | "srt" | "vtt" | "txt" | "other";

type ProductAction =
  | "app_opened"
  | "file_selected"
  | "processing_started"
  | "processing_completed"
  | "processing_failed"
  | "export_started"
  | "export_completed"
  | "export_failed"
  | "subtitle_saved"
  | "feedback_opened"
  | "feedback_submitted"
  | "feedback_failed";

type ActionOutcome = "observed" | "started" | "succeeded" | "failed";
type SafeErrorName =
  | "window_error"
  | "unhandled_rejection"
  | "network_error"
  | "request_timeout"
  | "upload_network_error"
  | "upload_timeout"
  | "invalid_response"
  | "http_4xx"
  | "http_5xx"
  | "unknown_error";

const ERROR_CODE_BUCKETS: Readonly<Record<string, SafeErrorName>> = {
  request_timeout: "request_timeout",
  upload_network_error: "upload_network_error",
  upload_timeout: "upload_timeout",
  invalid_response: "invalid_response",
};

const OBSERVABILITY_API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "production" ? "" : "http://localhost:8080");
let runtimePresenceId: string | null = null;

function currentRoute(): RouteBucket {
  if (typeof window === "undefined") return "other";
  const path = window.location.pathname;
  if (path === "/") return "studio";
  if (path.startsWith("/login") || path.startsWith("/register")) return "auth";
  if (path.startsWith("/account")) return "account";
  if (path.startsWith("/billing")) return "billing";
  if (path.startsWith("/admin/observability")) return "observability";
  if (path.startsWith("/privacy") || path.startsWith("/terms")) return "legal";
  return "other";
}

function viewportBucket(): ViewportBucket {
  if (typeof window === "undefined") return "regular";
  if (window.innerWidth < 640) return "compact";
  if (window.innerWidth >= 1200) return "wide";
  return "regular";
}

function authorizationHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function send(payload: Record<string, unknown>): Promise<void> {
  if (typeof window === "undefined") return;
  if (
    process.env.NODE_ENV === "test" &&
    process.env.NEXT_PUBLIC_ENABLE_TEST_OBSERVABILITY !== "1"
  )
    return;
  try {
    await fetch(`${OBSERVABILITY_API_BASE}/observability/events`, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: {
        "Content-Type": "application/json",
        ...authorizationHeaders(),
      },
      body: JSON.stringify(payload),
    });
  } catch {
    // Diagnostics are deliberately best-effort.
  }
}

function presenceId(): string {
  if (runtimePresenceId) return runtimePresenceId;
  runtimePresenceId =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}_runtime`;
  return runtimePresenceId;
}

export function reportPresence(): void {
  void send({
    kind: "presence",
    presence_id: presenceId(),
    route: currentRoute(),
    viewport: viewportBucket(),
  });
}

export function reportProductAction(
  name: ProductAction,
  options: { outcome?: ActionOutcome; exportFormat?: ExportFormat } = {},
): void {
  void send({
    kind: "action",
    name,
    outcome: options.outcome ?? "observed",
    export_format: options.exportFormat,
    route: currentRoute(),
    viewport: viewportBucket(),
  });
}

function endpointRoute(endpoint: string): RouteBucket {
  if (endpoint.startsWith("/auth")) return "auth";
  if (endpoint.startsWith("/billing")) return "billing";
  if (endpoint.startsWith("/feedback")) return "feedback";
  if (endpoint.startsWith("/history")) return "account";
  if (endpoint.startsWith("/videos")) return "studio";
  return "other";
}

function safeError(
  error: unknown,
): { name: SafeErrorName; statusCode?: number } | null {
  if (typeof error !== "object" || error === null)
    return { name: "unknown_error" };
  const value = error as { code?: unknown; status?: unknown };
  const code = typeof value.code === "string" ? value.code : "";
  const statusCode =
    typeof value.status === "number" ? value.status : undefined;
  if (code === "upload_cancelled") return null;
  if (ERROR_CODE_BUCKETS[code])
    return { name: ERROR_CODE_BUCKETS[code], statusCode };
  if (statusCode !== undefined) {
    if (statusCode >= 500) return { name: "http_5xx", statusCode };
    if (statusCode >= 400) return { name: "http_4xx", statusCode };
  }
  return { name: "network_error", statusCode };
}

export function reportApiFailure(endpoint: string, error: unknown): void {
  const normalized = safeError(error);
  if (!normalized) return;
  void send({
    kind: "api_error",
    name: normalized.name,
    status_code: normalized.statusCode,
    route: endpointRoute(endpoint),
    viewport: viewportBucket(),
  });
}

export function reportBrowserError(
  name: "window_error" | "unhandled_rejection",
): void {
  void send({
    kind: "frontend_error",
    name,
    route: currentRoute(),
    viewport: viewportBucket(),
  });
}

export function exportFormatBucket(resolution: string): ExportFormat {
  if (resolution === "720x1280") return "720p";
  if (resolution === "1080x1920") return "1080p";
  if (resolution === "2160x3840") return "4k";
  if (resolution === "srt" || resolution === "vtt" || resolution === "txt")
    return resolution;
  return "other";
}

export interface ObservabilitySnapshot {
  generated_at: number;
  retention_hours: number;
  active: {
    authenticated_accounts: number;
    guest_browser_sessions: number;
    estimated_total: number;
    window_seconds: number;
  };
  totals: Record<string, number>;
  jobs: Record<string, number>;
  actions: Array<{
    name: string;
    outcome: string;
    export_format: string | null;
    count: number;
  }>;
  errors: Array<{
    kind: string;
    name: string;
    route: string;
    status_code: number | null;
    count: number;
  }>;
  recent: Array<{
    ts: number;
    kind: string;
    name: string;
    route: string;
    auth_state: string;
    outcome?: string | null;
    export_format?: string | null;
    status_code?: number | null;
  }>;
}

export async function fetchObservabilitySnapshot(): Promise<ObservabilitySnapshot> {
  const response = await fetch(
    `${OBSERVABILITY_API_BASE}/observability/admin/snapshot`,
    {
      credentials: "include",
      cache: "no-store",
      headers: authorizationHeaders(),
    },
  );
  if (!response.ok)
    throw new Error(`observability_snapshot_${response.status}`);
  return response.json() as Promise<ObservabilitySnapshot>;
}
