global.fetch = jest.fn();

describe("API Client social, account, and error operations", () => {
  beforeEach(() => {
    (fetch as jest.Mock).mockClear();
    localStorage.clear();
    jest.resetModules();
  });

  describe("getTikTokAuthUrl", () => {
    it("should fetch TikTok auth URL", async () => {
      const mockResponse = {
        auth_url: "https://tiktok.com/auth",
        state: "abc123",
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.getTikTokAuthUrl();

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/tiktok/url"),
        expect.anything(),
      );
      expect(result.auth_url).toBe("https://tiktok.com/auth");
    });
  });

  describe("tiktokCallback", () => {
    it("should handle TikTok callback", async () => {
      const mockResponse = { access_token: "tiktok_token" };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.tiktokCallback("code123", "state123");

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/tiktok/callback"),
        expect.objectContaining({ method: "POST" }),
      );
      expect(result.access_token).toBe("tiktok_token");
    });
  });

  describe("uploadToTikTok", () => {
    it("should upload to TikTok", async () => {
      const mockResponse = { success: true };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.uploadToTikTok(
        "token",
        "/path/video.mp4",
        "Title",
        "Description",
      );

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/tiktok/upload"),
        expect.objectContaining({ method: "POST" }),
      );
      expect(result).toEqual({ success: true });
    });
  });

  describe("getGoogleAuthNonce", () => {
    it("should fetch a Google Identity Services nonce with the caller signal", async () => {
      const mockResponse = {
        nonce: "nonce-123",
        expires_in: 600,
        client_id: "google-client-id",
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });
      const controller = new AbortController();

      const { api } = await import("@/lib/api");
      const result = await api.getGoogleAuthNonce(controller.signal);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/google/nonce"),
        expect.objectContaining({ signal: controller.signal }),
      );
      expect(result.nonce).toBe("nonce-123");
    });
  });

  describe("googleLogin", () => {
    it("should exchange a verified Google ID token for a session", async () => {
      const mockResponse = {
        access_token: "google_token",
        token_type: "bearer",
        user_id: "456",
        name: "Google User",
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.googleLogin("signed-google-id-token");

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/google"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ id_token: "signed-google-id-token" }),
        }),
      );
      expect(result.access_token).toBe("google_token");
      expect(localStorage.getItem("auth_token")).toBe("google_token");
    });
  });

  describe("deleteAccount", () => {
    it("should delete account and clear token", async () => {
      localStorage.setItem("auth_token", "existing_token");
      localStorage.setItem("lastActiveJobId", "private-job");
      const mockResponse = { status: "ok", message: "Account deleted" };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      jest.resetModules();
      const { api } = await import("@/lib/api");
      const result = await api.deleteAccount();

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/me"),
        expect.objectContaining({ method: "DELETE" }),
      );
      expect(result.status).toBe("ok");
      expect(localStorage.getItem("auth_token")).toBeNull();
      expect(localStorage.getItem("lastActiveJobId")).toBeNull();
    });
  });

  describe("deleteJob", () => {
    it("should delete a job", async () => {
      const mockResponse = { status: "ok", job_id: "job-123" };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.deleteJob("job-123");

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/videos/jobs/job-123"),
        expect.objectContaining({ method: "DELETE" }),
      );
      expect(result.job_id).toBe("job-123");
    });
  });

  describe("deleteJobs", () => {
    it("should batch delete jobs using the backend route contract", async () => {
      const mockResponse = { status: "deleted", deleted_count: 2 };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.deleteJobs(["job-1", "job-2"]);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/videos/jobs/batch-delete"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ job_ids: ["job-1", "job-2"] }),
        }),
      );
      expect(result.deleted_count).toBe(2);
    });
  });

  describe("error handling", () => {
    it("should handle string error responses", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => "String error message",
      });

      const { api } = await import("@/lib/api");
      await expect(api.getCurrentUser()).rejects.toThrow(
        "String error message",
      );
    });

    it("should handle error.message format", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ message: "Message error" }),
      });

      const { api } = await import("@/lib/api");
      await expect(api.getCurrentUser()).rejects.toThrow("Message error");
    });

    it("should handle JSON parse failure gracefully", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => {
          throw new Error("Parse error");
        },
      });

      const { api } = await import("@/lib/api");
      await expect(api.getCurrentUser()).rejects.toThrow("Request failed");
    });

    it("should handle error object with detail as object", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: { info: "Complex error" } }),
      });

      const { api } = await import("@/lib/api");
      await expect(api.getCurrentUser()).rejects.toThrow(
        '{"info":"Complex error"}',
      );
    });

    it("should handle error with message property", async () => {
      (fetch as jest.Mock).mockResolvedValue({
        ok: false,
        json: async () => ({ message: "Error message prop" }),
      });
      const { api } = await import("@/lib/api");
      // Assuming we can use processVideo or simply check request generally
      // But we need to call something that uses request(). getCurrentUser does.
      await expect(api.getCurrentUser()).rejects.toThrow("Error message prop");
    });
  });
});
