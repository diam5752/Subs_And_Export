import { api } from "@/lib/api";
import { DIRECT_UPLOAD_MAX_BYTES, uploadInChunks } from "@/lib/chunkedUploads";

jest.mock("@/lib/chunkedUploads", () => ({
  DIRECT_UPLOAD_MAX_BYTES: 64 * 1024 * 1024,
  uploadInChunks: jest.fn(),
}));

it("routes a large file and the confirmed credit ceiling through resumable uploads", async () => {
  const file = new File(["video"], "Ελληνικό βίντεο.mp4", {
    type: "video/mp4",
  });
  Object.defineProperty(file, "size", { value: DIRECT_UPLOAD_MAX_BYTES + 1 });
  const callbacks = {
    onProgress: jest.fn(),
    signal: new AbortController().signal,
  };
  const job = { id: "reserved-job", status: "pending" };
  jest.mocked(uploadInChunks).mockResolvedValueOnce(job as never);
  await expect(
    api.processVideo(file, { authorized_credits: 30 }, callbacks),
  ).resolves.toBe(job);
  expect(uploadInChunks).toHaveBeenCalledWith(
    expect.objectContaining({
      request: expect.any(Function),
      upload: expect.any(Function),
    }),
    file,
    expect.objectContaining({ filename: file.name, authorized_credits: 30 }),
    callbacks,
  );
});
