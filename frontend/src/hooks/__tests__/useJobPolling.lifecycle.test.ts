import { act, renderHook } from "@testing-library/react";
import { api, type JobResponse } from "@/lib/api";
import { useJobPolling } from "../useJobPolling";

jest.mock("@/lib/api", () => ({ api: { getJobStatus: jest.fn() } }));

const t = (key: string) => key;
const callbacks = () => ({
  onProgress: jest.fn(),
  onComplete: jest.fn(),
  onFailed: jest.fn(),
  onError: jest.fn(),
});
const pending = {
  id: "current",
  status: "processing",
  progress: 10,
} as JobResponse;

async function advance(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  jest.mocked(api.getJobStatus).mockResolvedValue(pending);
});
afterEach(() => {
  jest.useRealTimers();
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
});

it("keeps one request in flight and waits after each response", async () => {
  let resolve!: (job: JobResponse) => void;
  jest.mocked(api.getJobStatus).mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const events = callbacks();
  renderHook(() => useJobPolling({ jobId: "current", callbacks: events, t }));
  await advance(10_000);
  expect(api.getJobStatus).toHaveBeenCalledTimes(1);
  await act(async () => {
    resolve(pending);
  });
  await advance(999);
  expect(api.getJobStatus).toHaveBeenCalledTimes(1);
  await advance(1);
  expect(api.getJobStatus).toHaveBeenCalledTimes(2);
});

it.each(["completed", "failed"])(
  "ignores a late %s response after switching jobs",
  async (status) => {
    let resolve!: (job: JobResponse) => void;
    jest.mocked(api.getJobStatus).mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const events = callbacks();
    const { rerender, result } = renderHook(
      ({ jobId }) => useJobPolling({ jobId, callbacks: events, t }),
      { initialProps: { jobId: "old" } },
    );
    await advance();
    rerender({ jobId: "current" });
    await advance();
    expect(api.getJobStatus).toHaveBeenLastCalledWith("current");
    await act(async () => {
      resolve({ ...pending, id: "old", status } as JobResponse);
    });
    expect(events.onComplete).not.toHaveBeenCalled();
    expect(events.onFailed).not.toHaveBeenCalled();
    expect(result.current.isPolling).toBe(true);
  },
);

it("updates callbacks without creating another request or losing a response", async () => {
  const first = callbacks();
  const second = callbacks();
  const { rerender } = renderHook(
    ({ events }) => useJobPolling({ jobId: "current", callbacks: events, t }),
    { initialProps: { events: first } },
  );
  await advance();
  rerender({ events: second });
  await advance();
  expect(api.getJobStatus).toHaveBeenCalledTimes(1);
  await advance(1000);
  expect(second.onProgress).toHaveBeenCalledTimes(1);
});

it("polls hidden tabs every 15 seconds and refreshes immediately when visible", async () => {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
  const events = callbacks();
  renderHook(() => useJobPolling({ jobId: "current", callbacks: events, t }));
  await advance(60_000);
  expect(api.getJobStatus).toHaveBeenCalledTimes(5);
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(api.getJobStatus).toHaveBeenCalledTimes(6);
});

it("can stop before the first scheduled request starts", async () => {
  const events = callbacks();
  const { result } = renderHook(() =>
    useJobPolling({ jobId: "current", callbacks: events, t }),
  );
  act(() => result.current.stopPolling());
  await advance(1000);
  expect(api.getJobStatus).not.toHaveBeenCalled();
  expect(result.current.isPolling).toBe(false);
});
