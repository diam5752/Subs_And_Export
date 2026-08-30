import {
  API_BASE,
  API_REQUEST_TIMEOUT_MS,
  STREAM_UPLOAD_METADATA_HEADER_MAX_CHARS,
  ApiError,
  encodeUtf8Base64,
  normalizedProcessVideoSettings,
  requireAuthorizedCredits,
  type ProcessVideoSettings,
  type UploadCallbacks,
} from "./apiCore";
import { ApiTransport } from "./apiTransport";
import type { ProcessingCreditTier } from "@/lib/points";
import type {
  ArtifactDownloadGrantResponse,
  BillingAdminPendingInvoicesResponse,
  BillingAdminPendingRefundsResponse,
  BillingAdminPendingWithdrawalsResponse,
  BillingPurchaseResponse,
  BillingCountry,
  BillingWithdrawalResponse,
  BillingWithdrawalResolutionResponse,
  ConsumerContractAcceptanceRequest,
  ConsumerContractLocale,
  CreditCatalogResponse,
  CreditCheckoutResponse,
  CreditCheckoutStatusResponse,
  ExportDataResponse,
  HistoryEvent,
  JobResponse,
  LogoutResponse,
  PaginatedJobsResponse,
  PointsBalanceResponse,
  ProductFeedbackPayload,
  ProductFeedbackResponse,
  RecordIssuedAadeDocumentPayload,
  RecordManualRefundAccountingPayload,
  RecordedAadeDocumentResponse,
  RecordedManualRefundAccountingResponse,
  ResolveBillingWithdrawalPayload,
  TokenResponse,
  TranscriptionCue,
  UserResponse,
} from "./apiTypes";

class ApiClient extends ApiTransport {
  async login(email: string, password: string): Promise<TokenResponse> {
    const formData = new URLSearchParams();
    formData.append("username", email);
    formData.append("password", password);

    const response = await this.request<TokenResponse>("/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formData,
    });
    this.setToken(response.access_token);
    return response;
  }

  async register(
    email: string,
    password: string,
    name: string,
  ): Promise<UserResponse> {
    return this.request<UserResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, name }),
    });
  }

  async getCurrentUser(): Promise<UserResponse> {
    return this.request<UserResponse>(
      "/auth/me",
      {},
      true,
      API_REQUEST_TIMEOUT_MS,
    );
  }

  async revokeSession(): Promise<LogoutResponse> {
    if (this.token) {
      try {
        return await this.request<LogoutResponse>(
          "/auth/logout",
          {
            method: "POST",
            keepalive: true,
          },
          true,
          API_REQUEST_TIMEOUT_MS,
        );
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) {
          throw error;
        }
      }
    }
    return this.request<LogoutResponse>(
      "/static/auth/logout",
      {
        method: "POST",
        keepalive: true,
      },
      false,
      API_REQUEST_TIMEOUT_MS,
    );
  }

  async getPointsBalance(): Promise<PointsBalanceResponse> {
    return this.request<PointsBalanceResponse>(
      "/auth/points",
      { cache: "no-store" },
      true,
      API_REQUEST_TIMEOUT_MS,
    );
  }

  async getCreditCatalog(
    locale: ConsumerContractLocale = "el",
  ): Promise<CreditCatalogResponse> {
    return this.request<CreditCatalogResponse>(
      `/billing/catalog?locale=${encodeURIComponent(locale)}`,
    );
  }

  async createCreditCheckout(
    packageKey: string,
    idempotencyKey: string,
    catalogVersion: string,
    billingCountry: BillingCountry,
    consumerContract: ConsumerContractAcceptanceRequest,
  ): Promise<CreditCheckoutResponse> {
    return this.request<CreditCheckoutResponse>("/billing/checkout", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        package_key: packageKey,
        catalog_version: catalogVersion,
        billing_country: billingCountry,
        consumer_contract: consumerContract,
      }),
    });
  }

  async getCreditCheckoutStatus(
    checkoutSessionId: string,
  ): Promise<CreditCheckoutStatusResponse> {
    return this.request<CreditCheckoutStatusResponse>(
      `/billing/checkout/${encodeURIComponent(checkoutSessionId)}`,
      { cache: "no-store" },
      true,
      API_REQUEST_TIMEOUT_MS,
    );
  }

  async listBillingPurchases(): Promise<BillingPurchaseResponse[]> {
    return this.request<BillingPurchaseResponse[]>("/billing/purchases");
  }

  async listPendingBillingInvoices(
    after?: string,
    limit: number = 50,
  ): Promise<BillingAdminPendingInvoicesResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (after) {
      params.set("after", after);
    }
    return this.request<BillingAdminPendingInvoicesResponse>(
      `/billing/admin/invoices/pending?${params.toString()}`,
      { cache: "no-store" },
    );
  }

  async recordIssuedAadeDocument(
    invoiceId: string,
    payload: RecordIssuedAadeDocumentPayload,
  ): Promise<RecordedAadeDocumentResponse> {
    return this.request<RecordedAadeDocumentResponse>(
      `/billing/admin/invoices/${encodeURIComponent(invoiceId)}/record-issued`,
      {
        method: "POST",
        cache: "no-store",
        body: JSON.stringify(payload),
      },
    );
  }

  async listPendingBillingRefunds(
    after?: string,
    limit: number = 50,
  ): Promise<BillingAdminPendingRefundsResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (after) {
      params.set("after", after);
    }
    return this.request<BillingAdminPendingRefundsResponse>(
      `/billing/admin/refunds/pending?${params.toString()}`,
      { cache: "no-store" },
    );
  }

  async recordManualRefundAccounting(
    reversalId: string,
    payload: RecordManualRefundAccountingPayload,
  ): Promise<RecordedManualRefundAccountingResponse> {
    return this.request<RecordedManualRefundAccountingResponse>(
      `/billing/admin/refunds/${encodeURIComponent(reversalId)}/record-aade-adjustment`,
      {
        method: "POST",
        cache: "no-store",
        body: JSON.stringify(payload),
      },
    );
  }

  async listPendingBillingWithdrawals(
    after?: string,
    limit: number = 50,
  ): Promise<BillingAdminPendingWithdrawalsResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (after) {
      params.set("after", after);
    }
    return this.request<BillingAdminPendingWithdrawalsResponse>(
      `/billing/admin/withdrawals/pending?${params.toString()}`,
      { cache: "no-store" },
    );
  }

  async resolveBillingWithdrawal(
    withdrawalId: string,
    payload: ResolveBillingWithdrawalPayload,
  ): Promise<BillingWithdrawalResolutionResponse> {
    return this.request<BillingWithdrawalResolutionResponse>(
      `/billing/admin/withdrawals/${encodeURIComponent(withdrawalId)}/resolve`,
      {
        method: "POST",
        cache: "no-store",
        body: JSON.stringify(payload),
      },
    );
  }

  async submitBillingWithdrawal(
    purchaseId: string,
    payload: {
      locale: ConsumerContractLocale;
      withdrawal_requested: true;
      confirmed_name: string;
      confirmation_email: string;
    },
    idempotencyKey: string,
  ): Promise<BillingWithdrawalResponse> {
    return this.request<BillingWithdrawalResponse>(
      `/billing/purchases/${encodeURIComponent(purchaseId)}/withdrawals`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload),
      },
    );
  }

  async downloadBillingArtifact(endpoint: string): Promise<Blob> {
    if (!endpoint.startsWith("/billing/purchases/")) {
      throw new Error("Invalid billing artifact path");
    }
    const headers: Record<string, string> = {};
    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }
    const response = await fetch(`${API_BASE}${endpoint}`, {
      credentials: "include",
      headers,
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({
        detail: "Billing artifact download failed",
      }));
      throw new Error(
        typeof errorData.detail === "string"
          ? errorData.detail
          : "Billing artifact download failed",
      );
    }
    return response.blob();
  }

  async processVideo(
    file: File,
    settings: ProcessVideoSettings,
    callbacks: UploadCallbacks = {},
  ): Promise<JobResponse> {
    const normalizedSettings = normalizedProcessVideoSettings(settings);
    const encodedMetadata = encodeUtf8Base64(
      JSON.stringify({
        filename: file.name,
        ...normalizedSettings,
      }),
    );
    if (
      !encodedMetadata ||
      encodedMetadata.length > STREAM_UPLOAD_METADATA_HEADER_MAX_CHARS
    ) {
      throw new ApiError(
        "Upload settings are too large to send safely. Shorten the context prompt and try again.",
        0,
        "upload_metadata_too_large",
      );
    }

    return this.uploadBody<JobResponse>(
      "/videos/process-stream",
      file,
      callbacks,
      {
        "Content-Type": file.type || "application/octet-stream",
        "X-Gsubs-Upload-Metadata": encodedMetadata,
      },
    );
  }

  async getJobStatus(jobId: string): Promise<JobResponse> {
    return this.request<JobResponse>(
      `/videos/jobs/${jobId}`,
      {},
      true,
      API_REQUEST_TIMEOUT_MS,
    );
  }

  async getJobs(): Promise<JobResponse[]> {
    return this.request<JobResponse[]>("/videos/jobs");
  }

  async getJobsPaginated(
    page: number = 1,
    pageSize: number = 5,
  ): Promise<PaginatedJobsResponse> {
    return this.request<PaginatedJobsResponse>(
      `/videos/jobs/paginated?page=${page}&page_size=${pageSize}`,
    );
  }

  async updateProfile(name: string): Promise<UserResponse> {
    return this.request<UserResponse>("/auth/me", {
      method: "PUT",
      body: JSON.stringify({ name }),
    });
  }

  async updatePassword(
    password: string,
    confirm_password: string,
  ): Promise<{ status: string }> {
    return this.request("/auth/password", {
      method: "PUT",
      body: JSON.stringify({ password, confirm_password }),
    });
  }

  async getHistory(limit: number = 50): Promise<HistoryEvent[]> {
    return this.request<HistoryEvent[]>(`/history/?limit=${limit}`);
  }

  async createProductFeedback(
    payload: ProductFeedbackPayload,
  ): Promise<ProductFeedbackResponse> {
    return this.request<ProductFeedbackResponse>(
      "/feedback",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      true,
      API_REQUEST_TIMEOUT_MS,
    );
  }

  async getTikTokAuthUrl(): Promise<{ auth_url: string; state: string }> {
    return this.request("/tiktok/url");
  }

  async tiktokCallback(
    code: string,
    state: string,
  ): Promise<{ access_token: string }> {
    return this.request("/tiktok/callback", {
      method: "POST",
      body: JSON.stringify({ code, state }),
    });
  }

  async uploadToTikTok(
    access_token: string,
    video_path: string,
    title: string,
    description: string,
  ): Promise<unknown> {
    return this.request("/tiktok/upload", {
      method: "POST",
      body: JSON.stringify({ access_token, video_path, title, description }),
    });
  }

  async getGoogleAuthNonce(signal?: AbortSignal): Promise<{
    nonce: string;
    expires_in: number;
    client_id: string;
  }> {
    return this.request("/auth/google/nonce", {
      credentials: "include",
      signal,
    });
  }

  async googleLogin(idToken: string): Promise<TokenResponse> {
    const response = await this.request<TokenResponse>("/auth/google", {
      method: "POST",
      credentials: "include",
      body: JSON.stringify({ id_token: idToken }),
    });
    this.setToken(response.access_token);
    return response;
  }

  async exportData(): Promise<ExportDataResponse> {
    return this.request<ExportDataResponse>("/auth/export");
  }

  async deleteAccount(): Promise<{ status: string; message: string }> {
    const response = await this.request<{ status: string; message: string }>(
      "/auth/me",
      {
        method: "DELETE",
      },
    );
    this.clearToken();
    return response;
  }

  async deleteJob(jobId: string): Promise<{ status: string; job_id: string }> {
    return this.request<{ status: string; job_id: string }>(
      `/videos/jobs/${jobId}`,
      {
        method: "DELETE",
      },
    );
  }

  async deleteJobs(
    jobIds: string[],
  ): Promise<{ status: string; deleted_count: number }> {
    return this.request<{ status: string; deleted_count: number }>(
      "/videos/jobs/batch-delete",
      {
        method: "POST",
        body: JSON.stringify({ job_ids: jobIds }),
      },
    );
  }

  async cancelJob(jobId: string): Promise<JobResponse> {
    return this.request<JobResponse>(`/videos/jobs/${jobId}/cancel`, {
      method: "POST",
    });
  }

  async exportVideo(
    jobId: string,
    resolution: string,
    settings?: {
      subtitle_position?: number;
      max_subtitle_lines?: number;
      subtitle_color?: string;
      shadow_strength?: number;
      highlight_style?: string;
      subtitle_size?: number;
      karaoke_enabled?: boolean;
      watermark_enabled?: boolean;
      video_quality?: string;
    },
  ): Promise<JobResponse> {
    return this.request<JobResponse>(`/videos/jobs/${jobId}/export`, {
      method: "POST",
      body: JSON.stringify({ resolution, ...settings }),
    });
  }

  async createArtifactDownloadGrant(
    jobId: string,
    artifactPath: string,
    filename: string,
  ): Promise<ArtifactDownloadGrantResponse> {
    return this.request<ArtifactDownloadGrantResponse>(
      `/videos/jobs/${encodeURIComponent(jobId)}/download-grant`,
      {
        method: "POST",
        cache: "no-store",
        body: JSON.stringify({
          artifact_path: artifactPath,
          filename,
        }),
      },
    );
  }

  async reprocessJob(
    jobId: string,
    settings: {
      authorized_credits: ProcessingCreditTier;
      transcribe_tier?: string;
      transcribe_provider?: string;
      openai_model?: string;
      video_quality?: string;
      video_resolution?: string;
      context_prompt?: string;
      subtitle_position?: number;
      max_subtitle_lines?: number;
      subtitle_color?: string | null;
      shadow_strength?: number;
      highlight_style?: string;
      subtitle_size?: number;
      karaoke_enabled?: boolean;
      watermark_enabled?: boolean;
    },
  ): Promise<JobResponse> {
    return this.request<JobResponse>(`/videos/jobs/${jobId}/reprocess`, {
      method: "POST",
      body: JSON.stringify({
        authorized_credits: requireAuthorizedCredits(
          settings.authorized_credits,
        ),
        transcribe_tier: settings.transcribe_tier || "standard",
        transcribe_provider: settings.transcribe_provider || "mock",
        openai_model: settings.openai_model || "",
        video_quality: settings.video_quality || "balanced",
        video_resolution: settings.video_resolution || "",
        context_prompt: settings.context_prompt || "",
        subtitle_position: settings.subtitle_position ?? 16,
        max_subtitle_lines: settings.max_subtitle_lines ?? 2,
        subtitle_color: settings.subtitle_color ?? null,
        shadow_strength: settings.shadow_strength ?? 4,
        highlight_style: settings.highlight_style || "karaoke",
        subtitle_size: settings.subtitle_size ?? 100,
        karaoke_enabled: settings.karaoke_enabled ?? true,
        watermark_enabled: settings.watermark_enabled ?? false,
      }),
    });
  }

  async updateJobTranscription(
    jobId: string,
    cues: TranscriptionCue[],
  ): Promise<{ status: string }> {
    return this.request<{ status: string }>(
      `/videos/jobs/${jobId}/transcription`,
      {
        method: "PUT",
        body: JSON.stringify({ cues }),
      },
    );
  }
}

export const api = new ApiClient();
