import {
  ApiError,
  uploadCancelledError,
  type UploadCallbacks,
} from "./apiCore";
import type { JobResponse } from "./apiTypes";

export const DIRECT_UPLOAD_MAX_BYTES = 64 * 1024 * 1024;
const MAX_CHUNK_BYTES = 16 * 1024 * 1024;

interface UploadSession {
  upload_id: string;
  size: number;
  offset: number;
  chunk_size: number;
  expires_at: number;
}

interface UploadTransport {
  request<T>(endpoint: string, options?: RequestInit): Promise<T>;
  upload<T>(
    endpoint: string,
    body: Blob,
    callbacks: UploadCallbacks,
    headers: Record<string, string>,
  ): Promise<T>;
}

function validateSession(session: UploadSession, size: number): UploadSession {
  if (
    !/^[0-9a-f-]{36}$/.test(session.upload_id) ||
    session.size !== size ||
    !Number.isSafeInteger(session.offset) ||
    session.offset < 0 ||
    session.offset > size ||
    !Number.isSafeInteger(session.chunk_size) ||
    session.chunk_size <= 0 ||
    session.chunk_size > MAX_CHUNK_BYTES
  ) {
    throw new ApiError("Invalid upload session", 0, "invalid_response");
  }
  return session;
}

function assertNotCancelled(signal?: AbortSignal): void {
  if (signal?.aborted) throw uploadCancelledError();
}

async function digestChunk(chunk: Blob): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    await chunk.arrayBuffer(),
  );
  return Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

function retryable(error: unknown): boolean {
  if (error instanceof TypeError) return true;
  return (
    error instanceof ApiError &&
    error.code !== "invalid_response" &&
    (error.status === 0 ||
      error.status === 408 ||
      error.status === 409 ||
      error.status === 429 ||
      error.status >= 500)
  );
}

async function retryRequest<T>(
  operation: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    assertNotCancelled(signal);
    try {
      return await operation();
    } catch (error) {
      assertNotCancelled(signal);
      if (attempt >= 2 || !retryable(error)) throw error;
      await new Promise((resolve) => setTimeout(resolve, 200 * 2 ** attempt));
    }
  }
}

async function uploadChunk(
  transport: UploadTransport,
  session: UploadSession,
  chunk: Blob,
  digest: string,
  fileSize: number,
  callbacks: UploadCallbacks,
): Promise<UploadSession> {
  const response = await transport.upload<UploadSession>(
    `/videos/uploads/${session.upload_id}/chunks`,
    chunk,
    {
      signal: callbacks.signal,
      onProgress: (progress) =>
        callbacks.onProgress?.(
          Math.round(
            ((session.offset + (chunk.size * progress) / 100) / fileSize) * 100,
          ),
        ),
    },
    {
      "Content-Type": "application/octet-stream",
      "X-Gsubs-Upload-Offset": String(session.offset),
      "X-Gsubs-Chunk-SHA256": digest,
    },
  );
  const updated = validateSession(response, fileSize);
  if (
    updated.upload_id !== session.upload_id ||
    updated.offset !== session.offset + chunk.size
  ) {
    throw new ApiError("Invalid upload offset", 0, "invalid_response");
  }
  return updated;
}

async function sendChunk(
  transport: UploadTransport,
  session: UploadSession,
  file: File,
  callbacks: UploadCallbacks,
): Promise<UploadSession> {
  const start = session.offset;
  const end = Math.min(file.size, start + session.chunk_size);
  const chunk = file.slice(start, end);
  const digest = await digestChunk(chunk);
  const endpoint = `/videos/uploads/${session.upload_id}`;
  for (let attempt = 0; ; attempt += 1) {
    assertNotCancelled(callbacks.signal);
    try {
      return await uploadChunk(
        transport,
        session,
        chunk,
        digest,
        file.size,
        callbacks,
      );
    } catch (error) {
      assertNotCancelled(callbacks.signal);
      if (attempt >= 2 || !retryable(error)) throw error;
      const refreshed = validateSession(
        await retryRequest(
          () =>
            transport.request<UploadSession>(endpoint, {
              signal: callbacks.signal,
            }),
          callbacks.signal,
        ),
        file.size,
      );
      if (refreshed.upload_id !== session.upload_id) throw error;
      if (refreshed.offset === end) return refreshed;
      if (refreshed.offset !== start) throw error;
      await new Promise((resolve) => setTimeout(resolve, 200 * 2 ** attempt));
    }
  }
}

export async function uploadInChunks(
  transport: UploadTransport,
  file: File,
  metadata: Record<string, unknown>,
  callbacks: UploadCallbacks,
): Promise<JobResponse> {
  assertNotCancelled(callbacks.signal);
  let session = validateSession(
    await transport.request<UploadSession>("/videos/uploads", {
      method: "POST",
      body: JSON.stringify({
        metadata,
        size: file.size,
        content_type: file.type || "application/octet-stream",
      }),
      signal: callbacks.signal,
    }),
    file.size,
  );
  const endpoint = `/videos/uploads/${session.upload_id}`;
  let submitted = false;
  try {
    while (session.offset < file.size) {
      session = await sendChunk(transport, session, file, callbacks);
      callbacks.onProgress?.(Math.round((session.offset / file.size) * 100));
    }
    assertNotCancelled(callbacks.signal);
    callbacks.onUploadComplete?.();
    // Retrying completion uses the same durable job and cannot charge twice.
    const result = await retryRequest(
      () =>
        transport.request<JobResponse>(`${endpoint}/complete`, {
          method: "POST",
          signal: callbacks.signal,
        }),
      callbacks.signal,
    );
    submitted = true;
    return result;
  } finally {
    if (!submitted) {
      // This is an authenticated upload reservation, not a completed project.
      // Use a fresh request so an aborted upload still releases its credits.
      await transport
        .request(endpoint, {
          method: "DELETE",
          signal: AbortSignal.timeout(12_000),
        })
        .catch(() => undefined);
    }
  }
}
