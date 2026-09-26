/** @jest-environment node */
import { File as NodeFile } from "node:buffer";
import { createHash, webcrypto } from "node:crypto";
import { ApiError, type UploadCallbacks } from "../apiCore";
import { uploadInChunks } from "../chunkedUploads";

const uploadId = "e81e64b9-778d-4d2f-bbe2-26cd61d5476e";
const endpoint = `/videos/uploads/${uploadId}`;
const job = { id: uploadId, status: "pending" };

function fixture() {
  const file = new NodeFile(["abcdefghij"], "clip.mp4", {
    type: "video/mp4",
  }) as unknown as File;
  const session = {
    upload_id: uploadId,
    size: file.size,
    offset: 0,
    chunk_size: 4,
    expires_at: Math.floor(Date.now() / 1000) + 900,
  };
  const request = jest.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/complete")) return job;
    if (options?.method === "DELETE") return { status: "cancelled" };
    return { ...session };
  });
  const upload = jest.fn(
    async (
      _path: string,
      body: Blob,
      callbacks: UploadCallbacks,
      headers: Record<string, string>,
    ) => {
      expect(headers["X-Gsubs-Upload-Offset"]).toBe(String(session.offset));
      const bytes = Buffer.from(await body.arrayBuffer());
      expect(headers["X-Gsubs-Chunk-SHA256"]).toBe(
        createHash("sha256").update(bytes).digest("hex"),
      );
      session.offset += body.size;
      callbacks.onProgress?.(100);
      return { ...session };
    },
  );
  const transport = {
    request: async <T>(path: string, options?: RequestInit) =>
      (await request(path, options)) as T,
    upload: async <T>(
      path: string,
      body: Blob,
      callbacks: UploadCallbacks,
      headers: Record<string, string>,
    ) => (await upload(path, body, callbacks, headers)) as T,
  };
  return { file, session, request, upload, transport };
}

beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  });
});

it("sends independent bounded chunks with integrity, offsets, and aggregate progress", async () => {
  const { file, request, upload, transport } = fixture();
  const onProgress = jest.fn();
  const onUploadComplete = jest.fn();
  const metadata = { filename: file.name, authorized_credits: 30 };
  await expect(
    uploadInChunks(transport, file, metadata, {
      onProgress,
      onUploadComplete,
    }),
  ).resolves.toEqual(job);
  expect(request).toHaveBeenNthCalledWith(
    1,
    "/videos/uploads",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ metadata, size: 10, content_type: "video/mp4" }),
    }),
  );
  expect(upload.mock.calls.map((call) => call[1].size)).toEqual([4, 4, 2]);
  expect(onProgress.mock.calls.map(([value]) => value)).toEqual([
    40, 40, 80, 80, 100, 100,
  ]);
  expect(onUploadComplete).toHaveBeenCalledTimes(1);
  expect(
    request.mock.calls.filter(([path]) => path.endsWith("/complete")),
  ).toHaveLength(1);
  expect(
    request.mock.calls.some(([, options]) => options?.method === "DELETE"),
  ).toBe(false);
});

it("reconciles a lost acknowledgement before sending the next chunk", async () => {
  const { file, session, upload, transport } = fixture();
  upload.mockImplementationOnce(async () => {
    session.offset = 4;
    throw new ApiError("connection lost after write", 0);
  });
  await expect(uploadInChunks(transport, file, {}, {})).resolves.toEqual(job);
  expect(
    upload.mock.calls.map((call) => call[3]["X-Gsubs-Upload-Offset"]),
  ).toEqual(["0", "4", "8"]);
});

it("retries an unacknowledged chunk without creating another reservation", async () => {
  const { file, request, upload, transport } = fixture();
  upload.mockRejectedValueOnce(new ApiError("temporary failure", 503));
  await expect(uploadInChunks(transport, file, {}, {})).resolves.toEqual(job);
  expect(
    upload.mock.calls.map((call) => call[3]["X-Gsubs-Upload-Offset"]),
  ).toEqual(["0", "0", "4", "8"]);
  expect(
    request.mock.calls.filter(([path]) => path === "/videos/uploads"),
  ).toHaveLength(1);
});

it("retries completion on the same job after a network failure", async () => {
  const { file, request, transport } = fixture();
  const original = request.getMockImplementation()!;
  let attempts = 0;
  request.mockImplementation(async (path, options) => {
    if (path.endsWith("/complete") && attempts++ === 0)
      throw new TypeError("network lost");
    return original(path, options);
  });
  await expect(uploadInChunks(transport, file, {}, {})).resolves.toEqual(job);
  expect(attempts).toBe(2);
  expect(
    request.mock.calls.some(([, options]) => options?.method === "DELETE"),
  ).toBe(false);
});

it("releases the reservation using a fresh signal after cancellation", async () => {
  const { file, request, upload, transport } = fixture();
  const controller = new AbortController();
  upload.mockImplementationOnce(async () => {
    controller.abort();
    throw new ApiError("cancelled", 0, "upload_cancelled");
  });
  await expect(
    uploadInChunks(
      transport,
      file,
      {},
      {
        signal: controller.signal,
      },
    ),
  ).rejects.toMatchObject({ code: "upload_cancelled" });
  const cleanup = request.mock.calls.find(
    ([, options]) => options?.method === "DELETE",
  );
  expect(cleanup?.[0]).toBe(endpoint);
  expect(cleanup?.[1]?.signal).not.toBe(controller.signal);
  expect(cleanup?.[1]?.signal?.aborted).toBe(false);
});

it("never starts a reservation for an already cancelled upload", async () => {
  const { file, request, transport } = fixture();
  const controller = new AbortController();
  controller.abort();
  await expect(
    uploadInChunks(
      transport,
      file,
      {},
      {
        signal: controller.signal,
      },
    ),
  ).rejects.toMatchObject({ code: "upload_cancelled" });
  expect(request).not.toHaveBeenCalled();
});

it.each([400, 401, 403, 410, 413])(
  "does not retry a permanent %s failure",
  async (status) => {
    const { file, request, upload, transport } = fixture();
    upload.mockRejectedValueOnce(new ApiError("rejected", status));
    await expect(uploadInChunks(transport, file, {}, {})).rejects.toMatchObject(
      { status },
    );
    expect(upload).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenLastCalledWith(
      endpoint,
      expect.objectContaining({ method: "DELETE" }),
    );
  },
);

it("bounds transient retries and still releases credits when they are exhausted", async () => {
  const { file, upload, request, transport } = fixture();
  upload.mockRejectedValue(new ApiError("unavailable", 503));
  await expect(uploadInChunks(transport, file, {}, {})).rejects.toMatchObject({
    status: 503,
  });
  expect(upload).toHaveBeenCalledTimes(3);
  expect(request).toHaveBeenLastCalledWith(
    endpoint,
    expect.objectContaining({ method: "DELETE" }),
  );
});

it("rejects a different upload identifier or invalid acknowledged offset", async () => {
  const { file, upload, session, transport } = fixture();
  upload.mockResolvedValueOnce({ ...session, offset: 9 });
  await expect(uploadInChunks(transport, file, {}, {})).rejects.toMatchObject({
    code: "invalid_response",
  });
  expect(upload).toHaveBeenCalledTimes(1);
});

it("does not let failed cleanup hide the original error", async () => {
  const { file, upload, request, transport } = fixture();
  const original = request.getMockImplementation()!;
  request.mockImplementation(async (path, options) => {
    if (options?.method === "DELETE") throw new TypeError("offline");
    return original(path, options);
  });
  upload.mockRejectedValueOnce(new ApiError("too large", 413));
  await expect(uploadInChunks(transport, file, {}, {})).rejects.toMatchObject({
    status: 413,
  });
});
