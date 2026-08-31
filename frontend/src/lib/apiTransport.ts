import { reportApiFailure } from "@/lib/observability";
import {
  API_BASE,
  ApiError,
  apiErrorFromPayload,
  parseXhrPayload,
  requestTimeoutError,
  throwReportedApiFailure,
  uploadCancelledError,
  uploadNetworkError,
  type UploadCallbacks,
} from "./apiCore";

interface RequestTimeoutState {
  signal: AbortSignal | null | undefined;
  triggered: boolean;
  clear: () => void;
}

function requestHeaders(
  options: RequestInit,
  token: string | null,
  includeBearer: boolean,
): Record<string, string> {
  const headers = options.headers
    ? { ...(options.headers as Record<string, string>) }
    : {};
  if (includeBearer && token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const bodyHasOwnContentType =
    options.body instanceof FormData || options.body instanceof URLSearchParams;
  if (!headers["Content-Type"] && !bodyHasOwnContentType) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

function requestTimeout(
  callerSignal: AbortSignal | null | undefined,
  timeoutMs: number | undefined,
): RequestTimeoutState {
  const state: RequestTimeoutState = {
    signal: callerSignal,
    triggered: false,
    clear: () => undefined,
  };
  if (callerSignal || timeoutMs === undefined) {
    return state;
  }

  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => {
    state.triggered = true;
    controller.abort();
  }, timeoutMs);
  state.signal = controller.signal;
  state.clear = () => globalThis.clearTimeout(timeoutId);
  return state;
}

async function decodeApiResponse<T>(
  response: Response,
  timeout: RequestTimeoutState,
): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }

  let errorData: unknown = { detail: "Request failed" };
  try {
    errorData = await response.json();
  } catch (error) {
    if (timeout.triggered) throw error;
  }
  throw apiErrorFromPayload(errorData, response.status, "Request failed");
}

export class ApiTransport {
  protected token: string | null = null;

  constructor() {
    /* istanbul ignore next */
    if (typeof window !== "undefined") {
      this.token = localStorage.getItem("auth_token");
    }
  }

  setToken(token: string): void {
    this.token = token;
    /* istanbul ignore next */
    if (typeof window !== "undefined") {
      localStorage.setItem("auth_token", token);
    }
  }

  clearToken(): void {
    this.token = null;
    /* istanbul ignore next */
    if (typeof window !== "undefined") {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("lastActiveJobId");
    }
  }

  protected async request<T>(
    endpoint: string,
    options: RequestInit = {},
    includeBearer = true,
    timeoutMs?: number,
  ): Promise<T> {
    const url = `${API_BASE}${endpoint}`;
    const headers = requestHeaders(options, this.token, includeBearer);
    const timeout = requestTimeout(options.signal, timeoutMs);

    try {
      const response = await fetch(url, {
        credentials: "include",
        ...options,
        headers,
        signal: timeout.signal,
      });
      return await decodeApiResponse<T>(response, timeout);
    } catch (error) {
      if (timeout.triggered) {
        return throwReportedApiFailure(endpoint, requestTimeoutError());
      }
      return throwReportedApiFailure(endpoint, error);
    } finally {
      timeout.clear();
    }
  }

  protected async uploadBody<T>(
    endpoint: string,
    body: FormData | Blob,
    callbacks: UploadCallbacks,
    headers: Record<string, string> = {},
  ): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const { onProgress, onUploadComplete, signal } = callbacks;
      let settled = false;

      const cleanup = () => {
        signal?.removeEventListener("abort", handleAbortSignal);
      };
      const resolveOnce = (value: T) => {
        if (settled) return;
        settled = true;
        cleanup();
        resolve(value);
      };
      const rejectOnce = (error: unknown) => {
        if (settled) return;
        settled = true;
        cleanup();
        reportApiFailure(endpoint, error);
        reject(error);
      };
      const handleAbortSignal = () => xhr.abort();

      xhr.open("POST", `${API_BASE}${endpoint}`);
      xhr.withCredentials = true;
      if (this.token) {
        xhr.setRequestHeader("Authorization", `Bearer ${this.token}`);
      }
      Object.entries(headers).forEach(([name, value]) => {
        xhr.setRequestHeader(name, value);
      });

      xhr.upload.onprogress = (event) => {
        if (!onProgress || !event.lengthComputable || event.total <= 0) return;
        onProgress(
          Math.min(100, Math.round((event.loaded / event.total) * 100)),
        );
      };
      xhr.upload.onload = () => onUploadComplete?.();
      xhr.onload = () => {
        const payload = parseXhrPayload(xhr);
        if (xhr.status >= 200 && xhr.status < 300) {
          if (payload === null) {
            rejectOnce(
              new ApiError(
                "Invalid server response",
                xhr.status,
                "invalid_response",
              ),
            );
            return;
          }
          resolveOnce(payload as T);
          return;
        }
        rejectOnce(apiErrorFromPayload(payload, xhr.status, "Upload failed"));
      };
      xhr.onerror = () =>
        rejectOnce(
          signal?.aborted ? uploadCancelledError() : uploadNetworkError(),
        );
      xhr.ontimeout = () =>
        rejectOnce(new ApiError("Upload timed out", 0, "upload_timeout"));
      xhr.onabort = () => rejectOnce(uploadCancelledError());

      if (signal?.aborted) {
        rejectOnce(uploadCancelledError());
        return;
      }
      signal?.addEventListener("abort", handleAbortSignal, { once: true });
      xhr.send(body);
    });
  }
}
