global.fetch = jest.fn();

describe("bounded API response reads", () => {
  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
    localStorage.clear();
  });

  it("keeps the timeout active until a successful JSON body is consumed", async () => {
    jest.useFakeTimers();
    try {
      (fetch as jest.Mock).mockImplementationOnce(
        (_url: string, options: RequestInit) =>
          Promise.resolve({
            ok: true,
            json: () =>
              new Promise((_resolve, reject) => {
                options.signal?.addEventListener("abort", () => {
                  const abortError = new Error("aborted while reading JSON");
                  abortError.name = "AbortError";
                  reject(abortError);
                });
              }),
          }),
      );

      const { API_REQUEST_TIMEOUT_MS, api } = await import("@/lib/api");
      const request = api.getPointsBalance();
      const assertion = expect(request).rejects.toMatchObject({
        name: "ApiError",
        status: 0,
        code: "request_timeout",
      });

      await jest.advanceTimersByTimeAsync(API_REQUEST_TIMEOUT_MS);
      await assertion;
    } finally {
      jest.useRealTimers();
    }
  });

  it("keeps the timeout active while an error JSON body is consumed", async () => {
    jest.useFakeTimers();
    try {
      (fetch as jest.Mock).mockImplementationOnce(
        (_url: string, options: RequestInit) =>
          Promise.resolve({
            ok: false,
            status: 502,
            json: () =>
              new Promise((_resolve, reject) => {
                options.signal?.addEventListener("abort", () =>
                  reject(new Error("aborted")),
                );
              }),
          }),
      );

      const { API_REQUEST_TIMEOUT_MS, api } = await import("@/lib/api");
      const request = api.getCreditCheckoutStatus("cs_test_stalled_error_body");
      const assertion = expect(request).rejects.toMatchObject({
        code: "request_timeout",
      });
      await jest.advanceTimersByTimeAsync(API_REQUEST_TIMEOUT_MS);
      await assertion;
    } finally {
      jest.useRealTimers();
    }
  });
});
