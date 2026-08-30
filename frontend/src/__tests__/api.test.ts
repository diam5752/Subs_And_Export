// Mock fetch globally
global.fetch = jest.fn();

describe("API Client", () => {
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

  it("uses relative same-origin endpoints when the production base is explicitly empty", async () => {
    process.env.NEXT_PUBLIC_API_URL = "";
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        access_token: "token",
        token_type: "bearer",
        user_id: "1",
        name: "QA",
      }),
    });

    const { API_BASE, api } = await import("@/lib/api");
    await api.login("qa@example.com", "password123");

    expect(API_BASE).toBe("");
    expect(fetch).toHaveBeenCalledWith(
      "/auth/token",
      expect.objectContaining({
        credentials: "include",
      }),
    );
  });

  describe("login", () => {
    it("should call the login endpoint with correct data", async () => {
      const mockResponse = {
        access_token: "test_token",
        token_type: "bearer",
        user_id: "123",
        name: "Test User",
        beta_credits_awarded: 30,
      };

      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.login("test@example.com", "password123");

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/token"),
        expect.objectContaining({
          method: "POST",
        }),
      );
      expect(result.access_token).toBe("test_token");
      expect(result.beta_credits_awarded).toBe(30);
      expect(localStorage.getItem("auth_token")).toBe("test_token");
    });

    it("should throw error on failed login", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: "Invalid credentials" }),
      });

      const { api } = await import("@/lib/api");
      await expect(api.login("test@example.com", "wrong")).rejects.toThrow(
        "Invalid credentials",
      );
    });
  });

  describe("register", () => {
    it("should call the register endpoint with correct data", async () => {
      const mockResponse = {
        id: "123",
        email: "test@example.com",
        name: "Test User",
        provider: "local",
      };

      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { api } = await import("@/lib/api");
      const result = await api.register(
        "test@example.com",
        "password123",
        "Test User",
      );

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/register"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            email: "test@example.com",
            password: "password123",
            name: "Test User",
          }),
        }),
      );
      expect(result.email).toBe("test@example.com");
    });
  });

  describe("getCurrentUser", () => {
    it("should include auth header when token exists", async () => {
      localStorage.setItem("auth_token", "stored_token");

      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: "123",
          email: "test@example.com",
          name: "Test",
          provider: "local",
        }),
      });

      jest.resetModules();
      const { api } = await import("@/lib/api");
      await api.getCurrentUser();

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/me"),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: "Bearer stored_token",
          }),
        }),
      );
    });

    it("aborts a stalled session lookup at the bounded JSON request timeout", async () => {
      // REGRESSION: an indefinitely pending fetch kept authenticated
      // browsers on the full-screen loading state forever.
      jest.useFakeTimers();
      try {
        (fetch as jest.Mock).mockImplementationOnce(
          (_url: string, options: RequestInit) =>
            new Promise((_resolve, reject) => {
              options.signal?.addEventListener("abort", () => {
                const abortError = new Error("aborted");
                abortError.name = "AbortError";
                reject(abortError);
              });
            }),
        );

        const { API_REQUEST_TIMEOUT_MS, api } = await import("@/lib/api");
        const request = api.getCurrentUser();
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
  });

  it("does not apply the session timeout to ordinary API operations", async () => {
    // Export and AI-backed requests can legitimately exceed the bounded
    // session-probe window, so the generic request path stays unbounded.
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ jobs: [] }),
    });

    const { api } = await import("@/lib/api");
    await api.exportData();

    const requestOptions = (fetch as jest.Mock).mock.calls[0][1] as RequestInit;
    expect(requestOptions.signal).toBeUndefined();
  });

  it.each([
    [
      "wallet",
      (client: typeof import("@/lib/api").api) => client.getPointsBalance(),
    ],
    [
      "checkout status",
      (client: typeof import("@/lib/api").api) =>
        client.getCreditCheckoutStatus("cs_test_paid"),
    ],
  ])(
    "bounds the authoritative %s read and bypasses browser caches",
    async (_label, request) => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ balance: 125 }),
      });

      const { api } = await import("@/lib/api");
      await request(api);

      const requestOptions = (fetch as jest.Mock).mock
        .calls[0][1] as RequestInit;
      expect(requestOptions.cache).toBe("no-store");
      expect(requestOptions.signal).toBeDefined();
    },
  );

  it("submits product feedback with a bounded request and optional bearer", async () => {
    localStorage.setItem("auth_token", "feedback-token");
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "received", id: "feedback-1" }),
    });
    jest.resetModules();
    const { api } = await import("@/lib/api");
    const payload = {
      category: "bug" as const,
      message: "The export stopped at the last step.",
      source_path: "/",
      page_title: "GSUBS",
      form_started_at: 1_800_000_000,
      website: "",
    };

    await expect(api.createProductFeedback(payload)).resolves.toEqual({
      status: "received",
      id: "feedback-1",
    });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/feedback"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({
          Authorization: "Bearer feedback-token",
        }),
        signal: expect.any(AbortSignal),
      }),
    );
  });

  describe("revokeSession", () => {
    it("posts the current bearer token to the server logout endpoint", async () => {
      localStorage.setItem("auth_token", "stored_token");
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: "success" }),
      });

      jest.resetModules();
      const { api } = await import("@/lib/api");
      await expect(api.revokeSession()).resolves.toEqual({
        status: "success",
      });

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/auth/logout"),
        expect.objectContaining({
          method: "POST",
          keepalive: true,
          headers: expect.objectContaining({
            Authorization: "Bearer stored_token",
          }),
        }),
      );
      expect(localStorage.getItem("auth_token")).toBe("stored_token");
    });

    it("reports a failed server revocation to its caller", async () => {
      localStorage.setItem("auth_token", "stored_token");
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: "Could not validate credentials" }),
      });

      jest.resetModules();
      const { api } = await import("@/lib/api");

      await expect(api.revokeSession()).rejects.toThrow(
        "Could not validate credentials",
      );
    });

    it("uses the cookie-scoped endpoint when no bearer is stored", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: "success" }),
      });

      const { api } = await import("@/lib/api");
      await expect(api.revokeSession()).resolves.toEqual({
        status: "success",
      });

      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/static/auth/logout"),
        expect.objectContaining({
          method: "POST",
          keepalive: true,
          credentials: "include",
          headers: expect.not.objectContaining({
            Authorization: expect.any(String),
          }),
        }),
      );
    });

    it("falls back to cookie-scoped logout after a rejected bearer", async () => {
      localStorage.setItem("auth_token", "stale-token");
      (fetch as jest.Mock)
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Could not validate credentials" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ status: "success" }),
        });

      jest.resetModules();
      const { api } = await import("@/lib/api");
      await expect(api.revokeSession()).resolves.toEqual({
        status: "success",
      });

      expect(fetch).toHaveBeenCalledTimes(2);
      expect(fetch).toHaveBeenNthCalledWith(
        1,
        expect.stringContaining("/auth/logout"),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: "Bearer stale-token",
          }),
        }),
      );
      expect(fetch).toHaveBeenNthCalledWith(
        2,
        expect.stringContaining("/static/auth/logout"),
        expect.objectContaining({
          headers: expect.not.objectContaining({
            Authorization: expect.any(String),
          }),
        }),
      );
    });

    it("does not mask a transient bearer logout failure with cookie fallback", async () => {
      localStorage.setItem("auth_token", "stored-token");
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({ detail: "Temporarily unavailable" }),
      });

      jest.resetModules();
      const { api } = await import("@/lib/api");

      await expect(api.revokeSession()).rejects.toThrow(
        "Temporarily unavailable",
      );
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it("preserves the HTTP status in a typed API error", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        status: 403,
        json: async () => ({
          detail: "Not authorized",
          code: "billing_admin_forbidden",
        }),
      });

      const { ApiError, api } = await import("@/lib/api");
      const request = api.listPendingBillingInvoices();

      await expect(request).rejects.toEqual(
        expect.objectContaining({
          name: "ApiError",
          message: "Not authorized [billing_admin_forbidden]",
          status: 403,
          code: "billing_admin_forbidden",
        }),
      );
      await request.catch((error: unknown) => {
        expect(error).toBeInstanceOf(ApiError);
      });
    });
  });

  describe("billing admin", () => {
    it("sends same-origin credentials when downloading a protected billing artifact", async () => {
      const artifact = new Blob(["contract"], { type: "application/pdf" });
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        blob: async () => artifact,
      });

      const { api } = await import("@/lib/api");
      await expect(
        api.downloadBillingArtifact("/billing/purchases/purchase-1/contract"),
      ).resolves.toBe(artifact);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/billing/purchases/purchase-1/contract"),
        expect.objectContaining({
          credentials: "include",
        }),
      );
    });

    it("lists the first page of pending AADE records with a bounded limit", async () => {
      const response = {
        items: [],
        count: 0,
        next_cursor: null,
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => response,
      });

      const { api } = await import("@/lib/api");
      await expect(api.listPendingBillingInvoices()).resolves.toEqual(response);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/billing/admin/invoices/pending?limit=50"),
        expect.objectContaining({
          cache: "no-store",
        }),
      );
    });

    it("encodes the server cursor when requesting the next pending page", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [], count: 0, next_cursor: null }),
      });

      const { api } = await import("@/lib/api");
      await api.listPendingBillingInvoices(
        `${1_800_000_000}:${"a".repeat(32)}`,
        25,
      );

      const requestedUrl = (fetch as jest.Mock).mock.calls[0][0] as string;
      expect(requestedUrl).toContain("/billing/admin/invoices/pending?");
      expect(requestedUrl).toContain("limit=25");
      expect(requestedUrl).toContain(`after=1800000000%3A${"a".repeat(32)}`);
    });

    it("records only the supplied already-issued AADE document data", async () => {
      const invoiceId = "a".repeat(32);
      const payload = {
        document_type: "11.2",
        series: "0",
        aa: "123",
        mark: "4000000000000123",
        issued_at: 1_800_000_000,
      };
      const response = {
        invoice_id: invoiceId,
        purchase_id: "b".repeat(32),
        document_status: "issued",
        aade_document_type: payload.document_type,
        aade_series: payload.series,
        aade_aa: payload.aa,
        aade_mark: payload.mark,
        issued_at: payload.issued_at,
        recorded_at: 1_800_000_001,
        financial_retention_until: 2_000_000_000,
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => response,
      });

      const { api } = await import("@/lib/api");
      await expect(
        api.recordIssuedAadeDocument(invoiceId, payload),
      ).resolves.toEqual(response);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining(
          `/billing/admin/invoices/${invoiceId}/record-issued`,
        ),
        expect.objectContaining({
          method: "POST",
          cache: "no-store",
          body: JSON.stringify(payload),
        }),
      );
    });

    it("encodes an invoice identifier instead of interpolating path separators", async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          invoice_id: "invalid",
          purchase_id: "b".repeat(32),
          document_status: "issued",
          aade_document_type: "11.2",
          aade_series: "0",
          aade_aa: "1",
          aade_mark: "2",
          issued_at: 1,
          recorded_at: 2,
          financial_retention_until: 2,
        }),
      });

      const { api } = await import("@/lib/api");
      await api.recordIssuedAadeDocument("unsafe/id", {
        document_type: "11.2",
        series: "0",
        aa: "1",
        mark: "2",
        issued_at: 1,
      });

      expect((fetch as jest.Mock).mock.calls[0][0]).toContain(
        "/billing/admin/invoices/unsafe%2Fid/record-issued",
      );
    });

    it("lists completed Stripe refunds awaiting AADE accounting without caching", async () => {
      const response = {
        items: [],
        count: 0,
        next_cursor: null,
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => response,
      });

      const { api } = await import("@/lib/api");
      await expect(
        api.listPendingBillingRefunds(`${1_800_000_000}:${"c".repeat(32)}`, 25),
      ).resolves.toEqual(response);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining(
          `/billing/admin/refunds/pending?limit=25&after=1800000000%3A${"c".repeat(32)}`,
        ),
        expect.objectContaining({
          cache: "no-store",
        }),
      );
    });

    it("records only the exact completed refund and AADE evidence payload", async () => {
      const reversalId = "unsafe/reversal";
      const payload = {
        original_document: null,
        adjustment_document: {
          document_type: "11.4",
          series: "ΠΙΣ",
          aa: "42",
          mark: "5000000000000042",
          issued_at: 1_800_000_100,
        },
        final_manual_actions_confirmed: true as const,
      };
      const response = {
        adjustment_id: "d".repeat(32),
        purchase_id: "e".repeat(32),
        reversal_id: "f".repeat(32),
        stripe_refund_id: "re_completed",
        amount_cents: 100,
        currency: "eur",
        aade_document_type: "11.4",
        aade_series: "ΠΙΣ",
        aade_aa: "42",
        aade_mark: "5000000000000042",
        issued_at: 1_800_000_100,
        recorded_at: 1_800_000_101,
        financial_retention_until: 2_000_000_000,
        original_invoice_status: "issued",
        original_invoice_mark: "4000000000000042",
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => response,
      });

      const { api } = await import("@/lib/api");
      await expect(
        api.recordManualRefundAccounting(reversalId, payload),
      ).resolves.toEqual(response);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining(
          "/billing/admin/refunds/unsafe%2Freversal/record-aade-adjustment",
        ),
        expect.objectContaining({
          method: "POST",
          cache: "no-store",
          body: JSON.stringify(payload),
        }),
      );
    });

    it("lists unresolved withdrawal requests without caching", async () => {
      const response = {
        items: [],
        count: 0,
        next_cursor: null,
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => response,
      });

      const { api } = await import("@/lib/api");
      await expect(
        api.listPendingBillingWithdrawals(
          `${1_800_000_200}:${"1".repeat(32)}`,
          10,
        ),
      ).resolves.toEqual(response);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining(
          `/billing/admin/withdrawals/pending?limit=10&after=1800000200%3A${"1".repeat(32)}`,
        ),
        expect.objectContaining({
          cache: "no-store",
        }),
      );
    });

    it("records one explicit human withdrawal decision without side effects", async () => {
      const withdrawalId = "unsafe/withdrawal";
      const payload = {
        decision: "accepted_refunded" as const,
        adjustment_id: "2".repeat(32),
        customer_explanation:
          "Το εγκεκριμένο refund και το διορθωτικό ολοκληρώθηκαν.",
        final_manual_review_confirmed: true as const,
      };
      const response = {
        resolution_id: "3".repeat(32),
        withdrawal_id: "4".repeat(32),
        purchase_id: "5".repeat(32),
        decision: "accepted_refunded" as const,
        reason_code: "accepted_after_manual_review",
        adjustment_id: payload.adjustment_id,
        resolved_at: 1_800_000_300,
        resolution_sha256: "a".repeat(64),
        resolution_url: "/billing/withdrawals/resolution",
      };
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => response,
      });

      const { api } = await import("@/lib/api");
      await expect(
        api.resolveBillingWithdrawal(withdrawalId, payload),
      ).resolves.toEqual(response);

      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining(
          "/billing/admin/withdrawals/unsafe%2Fwithdrawal/resolve",
        ),
        expect.objectContaining({
          method: "POST",
          cache: "no-store",
          body: JSON.stringify(payload),
        }),
      );
    });
  });
});
