// Mock fetch globally
global.fetch = jest.fn();

describe("API Client media and job operations", () => {
  const originalXMLHttpRequest = global.XMLHttpRequest;
  const originalApiBase = process.env.NEXT_PUBLIC_API_URL;

  beforeEach(() => {
    (fetch as jest.Mock).mockClear();
    localStorage.clear();
    jest.resetModules();
    global.XMLHttpRequest = originalXMLHttpRequest;
    if (originalApiBase === undefined) {
      delete process.env.NEXT_PUBLIC_API_URL;
    } else {
      process.env.NEXT_PUBLIC_API_URL = originalApiBase;
    }
  });

  describe("processVideo", () => {
    function installProcessXhr(status: number, payload: unknown) {
      const upload: {
        onprogress:
          | ((event: {
              lengthComputable: boolean;
              loaded: number;
              total: number;
            }) => void)
          | null;
        onload: (() => void) | null;
      } = {
        onprogress: null,
        onload: null,
      };
      const xhrMock = {
        open: jest.fn(),
        withCredentials: false,
        setRequestHeader: jest.fn(),
        send: jest.fn(),
        abort: jest.fn(),
        upload,
        status,
        responseText:
          typeof payload === "string" ? payload : JSON.stringify(payload),
        onload: null as null | (() => void),
        onerror: null as null | (() => void),
        ontimeout: null as null | (() => void),
        onabort: null as null | (() => void),
      };
      xhrMock.abort.mockImplementation(() => xhrMock.onabort?.());
      global.XMLHttpRequest = jest.fn(
        () => xhrMock,
      ) as unknown as typeof XMLHttpRequest;
      return xhrMock;
    }

    it("handles request failure with message property", async () => {
      const xhrMock = installProcessXhr(400, {
        message: "Custom error message",
      });
      const { api } = await import("@/lib/api");
      const file = new File(["video"], "test.mp4", { type: "video/mp4" });
      const promise = api.processVideo(file, { authorized_credits: 30 });

      xhrMock.onload?.();

      await expect(promise).rejects.toThrow("Custom error message");
    });

    it("handles request failure with string error", async () => {
      const xhrMock = installProcessXhr(400, "Generic error string");
      const { api } = await import("@/lib/api");
      const file = new File(["video"], "test.mp4", { type: "video/mp4" });
      const promise = api.processVideo(file, { authorized_credits: 30 });

      xhrMock.onload?.();

      await expect(promise).rejects.toThrow("Generic error string");
    });

    it("retains the authoritative structured quote-change contract", async () => {
      // REGRESSION: XHR failures previously flattened structured details
      // into a string, so the UI could not safely request reconfirmation.
      const xhrMock = installProcessXhr(409, {
        detail: "Processing quote changed",
        code: "PROCESSING_QUOTE_CHANGED",
        details: {
          duration_seconds: 180.001,
          required_credits: 60,
        },
      });
      const { api } = await import("@/lib/api");
      const file = new File(["video"], "boundary.mp4", { type: "video/mp4" });
      const promise = api.processVideo(file, { authorized_credits: 30 });

      xhrMock.onload?.();

      await expect(promise).rejects.toMatchObject({
        name: "ApiError",
        status: 409,
        code: "PROCESSING_QUOTE_CHANGED",
        details: {
          duration_seconds: 180.001,
          required_credits: 60,
        },
      });
    });

    it("uploads video with settings and reports browser upload progress", async () => {
      const mockResponse = {
        id: "job-123",
        status: "pending",
        progress: 0,
        message: null,
        created_at: Date.now(),
        updated_at: Date.now(),
        result_data: null,
      };
      const xhrMock = installProcessXhr(200, mockResponse);
      const { api } = await import("@/lib/api");
      const file = new File(["video"], "test.mp4", { type: "video/mp4" });
      const onProgress = jest.fn();
      const onUploadComplete = jest.fn();
      const promise = api.processVideo(
        file,
        {
          authorized_credits: 30,
          transcribe_tier: "standard",
          video_quality: "high",
        },
        { onProgress, onUploadComplete },
      );

      xhrMock.upload.onprogress?.({
        lengthComputable: true,
        loaded: 51,
        total: 100,
      });
      xhrMock.upload.onload?.();
      xhrMock.onload?.();
      const result = await promise;

      expect(xhrMock.open).toHaveBeenCalledWith(
        "POST",
        expect.stringContaining("/videos/process-stream"),
      );
      expect(xhrMock.withCredentials).toBe(true);
      expect(xhrMock.send).toHaveBeenCalledWith(file);
      expect(xhrMock.setRequestHeader).toHaveBeenCalledWith(
        "Content-Type",
        "video/mp4",
      );
      const metadataHeader = xhrMock.setRequestHeader.mock.calls.find(
        ([name]) => name === "X-Gsubs-Upload-Metadata",
      )?.[1] as string;
      const metadata = JSON.parse(
        Buffer.from(metadataHeader, "base64").toString("utf8"),
      ) as Record<string, unknown>;
      expect(metadata).toEqual(
        expect.objectContaining({
          filename: "test.mp4",
          authorized_credits: 30,
          transcribe_tier: "standard",
          video_quality: "high",
        }),
      );
      expect(onProgress).toHaveBeenCalledWith(51);
      expect(onUploadComplete).toHaveBeenCalledTimes(1);
      expect(result.id).toBe("job-123");
    });

    it("should use default settings when optional values are missing", async () => {
      const mockResponse = {
        id: "job-def",
        status: "pending",
        progress: 0,
        message: null,
        created_at: Date.now(),
        updated_at: Date.now(),
        result_data: null,
      };
      const xhrMock = installProcessXhr(200, mockResponse);
      const { api } = await import("@/lib/api");
      const file = new File(["video"], "default.mp4", { type: "video/mp4" });
      const promise = api.processVideo(file, { authorized_credits: 30 });

      xhrMock.onload?.();
      await promise;
      const metadataHeader = xhrMock.setRequestHeader.mock.calls.find(
        ([name]) => name === "X-Gsubs-Upload-Metadata",
      )?.[1] as string;
      const metadata = JSON.parse(
        Buffer.from(metadataHeader, "base64").toString("utf8"),
      ) as Record<string, unknown>;

      // Check defaults
      expect(metadata.transcribe_tier).toBe("standard");
      expect(metadata.transcribe_provider).toBe("mock");
      expect(metadata.video_quality).toBe("balanced");
      expect(metadata.subtitle_position).toBe(16);
      expect(metadata.max_subtitle_lines).toBe(2);
      expect(metadata.subtitle_size).toBe(100);
      expect(metadata.karaoke_enabled).toBe(true);
      expect(metadata.authorized_credits).toBe(30);
    });

    it("rejects a non-canonical credit ceiling before opening an upload", async () => {
      const xhrMock = installProcessXhr(200, { id: "never-used" });
      const { api } = await import("@/lib/api");
      const file = new File(["video"], "invalid-credit-ceiling.mp4", {
        type: "video/mp4",
      });

      await expect(
        api.processVideo(file, {
          authorized_credits: 45 as 30,
        }),
      ).rejects.toMatchObject({
        name: "ApiError",
        status: 0,
        code: "invalid_authorized_credits",
      });

      expect(global.XMLHttpRequest).not.toHaveBeenCalled();
      expect(xhrMock.open).not.toHaveBeenCalled();
      expect(xhrMock.send).not.toHaveBeenCalled();
    });

    it("fails locally before creating a request when metadata cannot safely fit in the header", async () => {
      const xhrMock = installProcessXhr(200, { id: "never-used" });
      const { api } = await import("@/lib/api");
      const file = new File(["video"], "oversized-settings.mp4", {
        type: "video/mp4",
      });

      await expect(
        api.processVideo(file, {
          authorized_credits: 30,
          context_prompt: "α".repeat(5000),
        }),
      ).rejects.toMatchObject({
        name: "ApiError",
        message:
          "Upload settings are too large to send safely. Shorten the context prompt and try again.",
        status: 0,
        code: "upload_metadata_too_large",
      });

      expect(global.XMLHttpRequest).not.toHaveBeenCalled();
      expect(xhrMock.open).not.toHaveBeenCalled();
      expect(xhrMock.send).not.toHaveBeenCalled();
    });

    it("aborts an in-flight upload without starting a second request", async () => {
      const xhrMock = installProcessXhr(200, { id: "never-used" });
      const controller = new AbortController();
      const { api } = await import("@/lib/api");
      const file = new File(["video"], "cancel.mp4", { type: "video/mp4" });
      const promise = api.processVideo(
        file,
        { authorized_credits: 30 },
        { signal: controller.signal },
      );

      controller.abort();

      await expect(promise).rejects.toMatchObject({ code: "upload_cancelled" });
      expect(xhrMock.abort).toHaveBeenCalledTimes(1);
      expect(xhrMock.send).toHaveBeenCalledTimes(1);
      expect(global.XMLHttpRequest).toHaveBeenCalledTimes(1);
    });
  });

  describe("reprocessJob", () => {
    it("sends the confirmed canonical credit ceiling in the JSON request", async () => {
      const response = {
        id: "reprocessed-job",
        status: "pending",
        progress: 0,
        message: null,
        created_at: Date.now(),
        updated_at: Date.now(),
        result_data: null,
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => response,
      });

      const { api } = await import("@/lib/api");
      await api.reprocessJob("source-job", {
        authorized_credits: 30,
        transcribe_provider: "mock",
        watermark_enabled: true,
      });

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/videos/jobs/source-job/reprocess"),
        expect.objectContaining({
          method: "POST",
          body: expect.any(String),
        }),
      );
      const request = (fetch as jest.Mock).mock.calls[0][1] as RequestInit;
      expect(JSON.parse(request.body as string)).toEqual(
        expect.objectContaining({
          authorized_credits: 30,
          transcribe_provider: "mock",
          watermark_enabled: true,
        }),
      );
    });

    it("retains authoritative quote details from a JSON reprocess response", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          detail: "Processing quote changed",
          code: "PROCESSING_QUOTE_CHANGED",
          details: {
            duration_seconds: 180.001,
            required_credits: 60,
          },
        }),
      });

      const { api } = await import("@/lib/api");
      await expect(
        api.reprocessJob("source-job", {
          authorized_credits: 30,
        }),
      ).rejects.toMatchObject({
        name: "ApiError",
        status: 409,
        code: "PROCESSING_QUOTE_CHANGED",
        details: {
          duration_seconds: 180.001,
          required_credits: 60,
        },
      });
    });

    it("rejects a non-canonical reprocess ceiling before making a request", async () => {
      const { api } = await import("@/lib/api");

      await expect(
        api.reprocessJob("source-job", {
          authorized_credits: 45 as 30,
        }),
      ).rejects.toMatchObject({
        name: "ApiError",
        status: 0,
        code: "invalid_authorized_credits",
      });

      expect(fetch).not.toHaveBeenCalled();
    });
  });

  describe("getJobStatus", () => {
    it("should fetch job status by id", async () => {
      const mockJob = {
        id: "job-123",
        status: "completed",
        progress: 100,
        message: "Done",
        created_at: Date.now(),
        updated_at: Date.now(),
        result_data: { video_path: "/path", artifacts_dir: "/artifacts" },
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockJob,
      });

      const { api } = await import("@/lib/api");
      const result = await api.getJobStatus("job-123");

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/videos/jobs/job-123"),
        expect.anything(),
      );
      const requestOptions = (fetch as jest.Mock).mock
        .calls[0][1] as RequestInit;
      expect(requestOptions.signal).toBeInstanceOf(AbortSignal);
      expect(result.status).toBe("completed");
    });
  });

  describe("createArtifactDownloadGrant", () => {
    it("requests an exact no-store cross-browser download URL", async () => {
      localStorage.setItem("auth_token", "stored_token");
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          download_url: "/static/artifacts/job-123/video.mp4?grant=signed",
          expires_in: 300,
        }),
      });
      jest.resetModules();
      const { api } = await import("@/lib/api");

      await expect(
        api.createArtifactDownloadGrant(
          "job-123",
          "/static/artifacts/job-123/video.mp4",
          "Δοκιμή_subs.mp4",
        ),
      ).resolves.toEqual({
        download_url: "/static/artifacts/job-123/video.mp4?grant=signed",
        expires_in: 300,
      });

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/videos/jobs/job-123/download-grant"),
        expect.objectContaining({
          method: "POST",
          cache: "no-store",
          credentials: "include",
          headers: expect.objectContaining({
            Authorization: "Bearer stored_token",
          }),
          body: JSON.stringify({
            artifact_path: "/static/artifacts/job-123/video.mp4",
            filename: "Δοκιμή_subs.mp4",
          }),
        }),
      );
    });
  });

  describe("updateJobTranscription", () => {
    it("should update transcription cues for a job", async () => {
      const mockResponse = { status: "ok" };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const cues = [
        {
          start: 0,
          end: 1,
          text: "hello world",
          words: [{ start: 0, end: 1, text: "hello" }],
        },
      ];
      const result = await api.updateJobTranscription("job-123", cues);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/videos/jobs/job-123/transcription"),
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ cues }),
        }),
      );
      expect(result.status).toBe("ok");
    });
  });

  describe("getJobs", () => {
    it("should fetch all jobs", async () => {
      const mockJobs = [
        {
          id: "job-1",
          status: "completed",
          progress: 100,
          message: null,
          created_at: Date.now(),
          updated_at: Date.now(),
          result_data: null,
        },
      ];
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockJobs,
      });

      const { api } = await import("@/lib/api");
      const result = await api.getJobs();

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/videos/jobs"),
        expect.anything(),
      );
      expect(result).toHaveLength(1);
    });
  });

  describe("updateProfile", () => {
    it("should update user profile", async () => {
      const mockResponse = {
        id: "123",
        email: "test@example.com",
        name: "New Name",
        provider: "local",
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.updateProfile("New Name");

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/me"),
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ name: "New Name" }),
        }),
      );
      expect(result.name).toBe("New Name");
    });
  });

  describe("updatePassword", () => {
    it("should update password", async () => {
      const mockResponse = { status: "ok" };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.updatePassword("newpass", "newpass");

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/password"),
        expect.objectContaining({ method: "PUT" }),
      );
      expect(result.status).toBe("ok");
    });
  });

  describe("getHistory", () => {
    it("should fetch history events with custom limit", async () => {
      const mockHistory = [
        {
          ts: "2024-01-01",
          user_id: "123",
          email: "test@test.com",
          kind: "video_processed",
          summary: "Test",
          data: {},
        },
      ];
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockHistory,
      });

      const { api } = await import("@/lib/api");
      const result = await api.getHistory(10);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/history/?limit=10"),
        expect.anything(),
      );
      expect(result).toHaveLength(1);
    });

    it("should fetch history events with default limit", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      });
      const { api } = await import("@/lib/api");
      await api.getHistory();
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/history/?limit=50"),
        expect.anything(),
      );
    });
  });
});

describe("Token Management", () => {
  beforeEach(() => {
    localStorage.clear();
    jest.resetModules();
  });

  it("should store token in localStorage", async () => {
    const { api } = await import("@/lib/api");
    api.setToken("new_token");
    expect(localStorage.getItem("auth_token")).toBe("new_token");
  });

  it("should clear token from localStorage", async () => {
    localStorage.setItem("auth_token", "existing_token");
    const { api } = await import("@/lib/api");
    api.clearToken();
    expect(localStorage.getItem("auth_token")).toBeNull();
  });
});
