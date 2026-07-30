// An explicitly empty production value keeps every API request same-origin.
// That makes the standalone image portable across verified hostnames without
// rebuilding it for each public URL. Development still keeps its local API
// fallback when the variable is completely absent.
export const API_BASE = process.env.NEXT_PUBLIC_API_URL
    ?? (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:8080');

export class ApiError extends Error {
    readonly status: number;
    readonly code: string | null;

    constructor(message: string, status: number, code: string | null = null) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
    }
}

interface UploadCallbacks {
    onProgress?: (percent: number) => void;
    onRetry?: (nextAttempt: number, maxAttempts: number) => void;
    onUploadComplete?: () => void;
    signal?: AbortSignal;
}

interface ProcessVideoSettings {
    transcribe_tier?: string;
    transcribe_provider?: string;
    openai_model?: string;
    video_quality?: string;
    video_resolution?: string;
    use_llm?: boolean;
    context_prompt?: string;
    subtitle_position?: number;
    max_subtitle_lines?: number;
    subtitle_color?: string;
    shadow_strength?: number;
    highlight_style?: string;
    subtitle_size?: number;
    karaoke_enabled?: boolean;
    watermark_enabled?: boolean;
}

const SIGNED_UPLOAD_MAX_ATTEMPTS = 3;
const SIGNED_UPLOAD_RETRY_BASE_DELAY_MS = 500;
const STREAM_UPLOAD_METADATA_HEADER_MAX_CHARS = 8_000;

function encodeUtf8Base64(value: string): string | null {
    try {
        const binary = encodeURIComponent(value).replace(
            /%([0-9A-F]{2})/g,
            (_match, hex: string) => String.fromCharCode(Number.parseInt(hex, 16)),
        );
        return btoa(binary);
    } catch {
        return null;
    }
}

function normalizedProcessVideoSettings(settings: ProcessVideoSettings) {
    return {
        transcribe_tier: settings.transcribe_tier || 'standard',
        transcribe_provider: settings.transcribe_provider || 'mock',
        openai_model: settings.openai_model || '',
        video_quality: settings.video_quality || 'balanced',
        video_resolution: settings.video_resolution || '',
        use_llm: Boolean(settings.use_llm),
        context_prompt: settings.context_prompt || '',
        subtitle_position: settings.subtitle_position ?? 16,
        max_subtitle_lines: settings.max_subtitle_lines ?? 2,
        subtitle_color: settings.subtitle_color ?? null,
        shadow_strength: settings.shadow_strength ?? 4,
        highlight_style: settings.highlight_style || 'karaoke',
        subtitle_size: settings.subtitle_size ?? 100,
        karaoke_enabled: settings.karaoke_enabled ?? true,
        watermark_enabled: settings.watermark_enabled ?? false,
    };
}


function uploadCancelledError(): ApiError {
    return new ApiError('Upload cancelled', 0, 'upload_cancelled');
}

function uploadNetworkError(): ApiError {
    return new ApiError('Upload failed', 0, 'upload_network_error');
}

function parseXhrPayload(xhr: XMLHttpRequest): unknown {
    if (typeof xhr.response === 'object' && xhr.response !== null) {
        return xhr.response;
    }
    const responseText = typeof xhr.responseText === 'string' ? xhr.responseText : '';
    if (!responseText) return null;
    try {
        return JSON.parse(responseText) as unknown;
    } catch {
        return responseText;
    }
}

function apiErrorFromPayload(
    payload: unknown,
    status: number,
    fallbackMessage: string,
): ApiError {
    let message = fallbackMessage;
    let code: string | null = null;

    if (typeof payload === 'string' && payload) {
        message = payload;
    } else if (typeof payload === 'object' && payload !== null) {
        const errorData = payload as Record<string, unknown>;
        if (typeof errorData.detail === 'string') {
            message = errorData.detail;
        } else if (errorData.detail !== undefined) {
            message = JSON.stringify(errorData.detail);
        } else if (typeof errorData.message === 'string') {
            message = errorData.message;
        }
        if (typeof errorData.code === 'string') {
            code = errorData.code;
            if (errorData.detail !== undefined) {
                message += ` [${errorData.code}]`;
            }
        }
    }

    return new ApiError(message, status, code);
}

function isRetryableSignedUploadError(error: unknown): boolean {
    return error instanceof ApiError
        && (
            error.code === 'upload_network_error'
            || error.code === 'upload_timeout'
            || error.status === 408
            || error.status === 429
            || error.status >= 500
        );
}

async function waitForUploadRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) throw uploadCancelledError();

    await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
            signal?.removeEventListener('abort', handleAbort);
            resolve();
        }, delayMs);
        const handleAbort = () => {
            clearTimeout(timeout);
            reject(uploadCancelledError());
        };
        signal?.addEventListener('abort', handleAbort, { once: true });
    });
}

interface TokenResponse {
    access_token: string;
    token_type: string;
    user_id: string;
    name: string;
}

interface JobResultData {
    video_path: string;
    artifacts_dir: string;
    public_url?: string;
    artifact_url?: string;
    transcription_url?: string;
    source_gcs_object?: string;
    social?: string | null;
    original_filename?: string | null;
    video_crf?: number;
    transcribe_tier?: string;
    transcribe_provider?: string;
    output_size?: number;
    duration_seconds?: number;
    resolution?: string;
    variants?: Record<string, string>;
    files_missing?: boolean;
}

export interface JobResponse {
    id: string;
    status: string;
    progress: number;
    message: string | null;
    created_at: number;
    updated_at: number;
    expires_at?: number | null;
    result_data: JobResultData | null;
    balance?: number | null;
}

interface GcsUploadUrlResponse {
    upload_id: string;
    object_name: string;
    upload_url: string;
    expires_at: number;
    required_headers: Record<string, string>;
}

interface HistoryEvent {
    ts: string;
    user_id: string;
    email: string;
    kind: string;
    summary: string;
    data: Record<string, unknown>;
}

interface UserResponse {
    id: string;
    email: string;
    name: string;
    provider: string;
    avatar_url: string | null;
}

interface LogoutResponse {
    status: 'success';
}

export interface PointsBalanceResponse {
    balance: number;
    paid_balance: number;
    promotional_balance: number;
    reversal_debt: number;
    ai_spendable_balance: number;
}

export interface CreditPackage {
    key: string;
    credits: number;
    amount_eur_cents: number;
    featured: boolean;
}

type ConsumerContractLocale = 'el' | 'en';
type BillingCountry = 'GR';

export interface ConsumerContractDisclosure {
    schema_version: number;
    status: string;
    classification: string;
    disclosure_id: string;
    disclosure_sha256: string;
    locale: ConsumerContractLocale;
    policy_version: string;
    terms_version: string;
    withdrawal_notice_version: string;
    confirmation_template_version: string;
    terms_url: string;
    withdrawal_url: string;
    model_withdrawal_form_url: string;
    trader: {
        name: string;
        service: string;
        support_email: string;
    };
    content: {
        title: string;
        service_description: string;
        credit_description: string;
        purchase_terms: string;
        delivery_timing: string;
        validity_and_transfer: string;
        functionality: string;
        compatibility: string;
        withdrawal_notice: string;
        manual_review_notice: string;
    };
    required_acceptances: {
        terms: string;
        immediate_performance: string;
        withdrawal_consequences: string;
    };
}

interface ConsumerContractAcceptanceRequest {
    disclosure_id: string;
    disclosure_sha256: string;
    locale: ConsumerContractLocale;
    policy_version: string;
    terms_version: string;
    withdrawal_notice_version: string;
    terms_accepted: true;
    immediate_performance_requested: true;
    withdrawal_consequences_acknowledged: true;
}

export interface VideoCreditBracket {
    key: string;
    max_duration_seconds: number;
    credits: number;
}

export interface CreditCatalogResponse {
    catalog_version: string;
    currency: string;
    billing_country_scope: BillingCountry[];
    checkout_enabled: boolean;
    consumer_contract_status: 'approved' | 'unavailable_unapproved';
    consumer_contract: ConsumerContractDisclosure | null;
    packages: CreditPackage[];
    video_pricing: VideoCreditBracket[];
}

interface CreditCheckoutResponse {
    purchase_id: string;
    checkout_session_id: string | null;
    checkout_url: string | null;
    status: string;
}

interface CreditCheckoutStatusResponse {
    purchase_id: string;
    package_key: string;
    credits: number;
    amount_eur_cents: number;
    status: string;
    checkout_session_id: string | null;
    wallet: PointsBalanceResponse;
}

export interface BillingPurchaseResponse {
    purchase_id: string;
    package_key: string;
    credits: number;
    amount_eur_cents: number;
    currency: string;
    status: string;
    created_at: number;
    fulfilled_at: number | null;
    contract_confirmation_available: boolean;
    contract_confirmation_url: string | null;
    contract_concluded_at: number | null;
    withdrawal_action_available: boolean;
    withdrawal_status: string | null;
    withdrawal_acknowledgement_available: boolean;
    withdrawal_acknowledgement_url: string | null;
    withdrawal_resolution_available: boolean;
    withdrawal_resolution_decision: BillingWithdrawalResolutionDecision | null;
    withdrawal_resolution_url: string | null;
}

export interface BillingAdminPackage {
    key: string | null;
    credits: number | null;
}

export interface BillingAdminPayment {
    checkout_session_id: string | null;
    payment_intent_id: string | null;
    confirmed_at: number | null;
    livemode: boolean | null;
    amount_paid_cents: number | null;
    currency: string | null;
    payment_status: string | null;
}

export interface BillingAdminCustomer {
    name: string | null;
    email: string | null;
    country: string | null;
    city: string | null;
    postal_code: string | null;
    line1: string | null;
    line2: string | null;
    state: string | null;
    status: string | null;
    missing_required_fields: string[];
}

export interface BillingAdminTax {
    gross_amount_cents: number | null;
    net_amount_cents: number | null;
    vat_amount_cents: number | null;
    vat_rate_percent: number | null;
}

export interface BillingAdminService {
    code: string | null;
    name: string | null;
}

export interface BillingAdminPendingInvoice {
    invoice_id: string;
    purchase_id: string;
    document_status: string;
    purchase_status: string;
    provider: string;
    document_kind: string;
    refunded_amount_cents: number;
    reversed_amount_cents: number;
    reversed_credits: number;
    dispute_active: boolean;
    requires_reversal_review: boolean;
    aade_document_type: string | null;
    aade_series: string | null;
    aade_aa: string | null;
    aade_mark: string | null;
    issued_at: number | null;
    recorded_at: number | null;
    created_at: number;
    financial_retention_until: number;
    package: BillingAdminPackage;
    payment: BillingAdminPayment | null;
    customer: BillingAdminCustomer | null;
    tax: BillingAdminTax;
    service: BillingAdminService;
}

interface BillingAdminPendingInvoicesResponse {
    items: BillingAdminPendingInvoice[];
    count: number;
    next_cursor: string | null;
}

interface RecordIssuedAadeDocumentPayload {
    document_type: string;
    series: string;
    aa: string;
    mark: string;
    issued_at: number;
}

export interface RecordedAadeDocumentResponse {
    invoice_id: string;
    purchase_id: string;
    document_status: string;
    aade_document_type: string;
    aade_series: string;
    aade_aa: string;
    aade_mark: string;
    issued_at: number;
    recorded_at: number;
    financial_retention_until: number;
}

export interface BillingAdminPendingRefund {
    reversal_id: string;
    stripe_refund_id: string;
    stripe_refund_status: string;
    stripe_refund_created_at: number;
    amount_cents: number;
    currency: string;
    linked_withdrawal_id: string | null;
    original_invoice: BillingAdminPendingInvoice;
}

interface BillingAdminPendingRefundsResponse {
    items: BillingAdminPendingRefund[];
    count: number;
    next_cursor: string | null;
}

interface RecordManualRefundAccountingPayload {
    original_document: RecordIssuedAadeDocumentPayload | null;
    adjustment_document: RecordIssuedAadeDocumentPayload;
    final_manual_actions_confirmed: true;
}

export interface RecordedManualRefundAccountingResponse {
    adjustment_id: string;
    purchase_id: string;
    reversal_id: string;
    stripe_refund_id: string;
    amount_cents: number;
    currency: string;
    aade_document_type: string;
    aade_series: string;
    aade_aa: string;
    aade_mark: string;
    issued_at: number;
    recorded_at: number;
    financial_retention_until: number;
    original_invoice_status: string;
    original_invoice_mark: string;
}

export interface BillingAdminWithdrawalAdjustment {
    adjustment_id: string;
    stripe_refund_id: string;
    amount_cents: number;
    currency: string;
    aade_document_type: string;
    aade_series: string;
    aade_aa: string;
    aade_mark: string;
    issued_at: number;
}

export interface BillingAdminPendingWithdrawal {
    withdrawal_id: string;
    purchase_id: string;
    locale: ConsumerContractLocale;
    submitted_at: number;
    contract_concluded_at: number;
    confirmed_name: string;
    confirmation_email: string;
    available_adjustments: BillingAdminWithdrawalAdjustment[];
}

interface BillingAdminPendingWithdrawalsResponse {
    items: BillingAdminPendingWithdrawal[];
    count: number;
    next_cursor: string | null;
}

export type BillingWithdrawalResolutionDecision =
    | 'accepted_refunded'
    | 'rejected';

interface ResolveBillingWithdrawalPayload {
    decision: BillingWithdrawalResolutionDecision;
    adjustment_id: string | null;
    customer_explanation: string;
    final_manual_review_confirmed: true;
}

export interface BillingWithdrawalResolutionResponse {
    resolution_id: string;
    withdrawal_id: string;
    purchase_id: string;
    decision: BillingWithdrawalResolutionDecision;
    reason_code: string;
    adjustment_id: string | null;
    resolved_at: number;
    resolution_sha256: string;
    resolution_url: string;
}

interface BillingWithdrawalResponse {
    withdrawal_id: string;
    purchase_id: string;
    status: string;
    submitted_at: number;
    timeliness_assessment_status: 'pending_manual_review';
    acknowledgement_sha256: string;
    acknowledgement_url: string;
}

interface ExportDataResponse {
    profile: UserResponse;
    jobs: JobResponse[];
    history: HistoryEvent[];
    billing_purchases: Record<string, unknown>[];
    wallet: Record<string, unknown> | null;
    point_transactions: Record<string, unknown>[];
    usage_ledger: Record<string, unknown>[];
    token_usage: Record<string, unknown>[];
    provider_budget_reservations: Record<string, unknown>[];
    gcs_uploads: Record<string, unknown>[];
    sessions: Record<string, unknown>[];
    oauth_states: Record<string, unknown>[];
}



interface PaginatedJobsResponse {
    items: JobResponse[];
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
}

export interface TranscriptionWordTiming {
    start: number;
    end: number;
    text: string;
}

export interface TranscriptionCue {
    start: number;
    end: number;
    text: string;
    words?: TranscriptionWordTiming[] | null;
}





class ApiClient {
    private token: string | null = null;

    constructor() {
        /* istanbul ignore next */
        if (typeof window !== 'undefined') {
            this.token = localStorage.getItem('auth_token');
        }
    }

    setToken(token: string) {
        this.token = token;
        /* istanbul ignore next */
        if (typeof window !== 'undefined') {
            localStorage.setItem('auth_token', token);
        }
    }

    clearToken() {
        this.token = null;
        /* istanbul ignore next */
        if (typeof window !== 'undefined') {
            localStorage.removeItem('auth_token');
        }
    }

    private async request<T>(
        endpoint: string,
        options: RequestInit = {}
    ): Promise<T> {
        const url = `${API_BASE}${endpoint}`;
        const headers: Record<string, string> = {};

        // Copy existing headers
        if (options.headers) {
            const existingHeaders = options.headers as Record<string, string>;
            Object.keys(existingHeaders).forEach(key => {
                headers[key] = existingHeaders[key];
            });
        }

        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        // Only set Content-Type to JSON if not already set and body is not FormData/URLSearchParams
        if (!headers['Content-Type'] &&
            !(options.body instanceof FormData) &&
            !(options.body instanceof URLSearchParams)) {
            headers['Content-Type'] = 'application/json';
        }

        const response = await fetch(url, { ...options, headers });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
            throw apiErrorFromPayload(errorData, response.status, 'Request failed');
        }

        return response.json();
    }

    private async uploadBody<T>(
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
                signal?.removeEventListener('abort', handleAbortSignal);
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
                reject(error);
            };
            const handleAbortSignal = () => xhr.abort();

            xhr.open('POST', `${API_BASE}${endpoint}`);
            if (this.token) {
                xhr.setRequestHeader('Authorization', `Bearer ${this.token}`);
            }
            Object.entries(headers).forEach(([name, value]) => {
                xhr.setRequestHeader(name, value);
            });

            xhr.upload.onprogress = (event) => {
                if (!onProgress || !event.lengthComputable || event.total <= 0) return;
                onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
            };
            xhr.upload.onload = () => onUploadComplete?.();
            xhr.onload = () => {
                const payload = parseXhrPayload(xhr);
                if (xhr.status >= 200 && xhr.status < 300) {
                    if (payload === null) {
                        rejectOnce(new ApiError('Invalid server response', xhr.status, 'invalid_response'));
                        return;
                    }
                    resolveOnce(payload as T);
                    return;
                }
                rejectOnce(apiErrorFromPayload(payload, xhr.status, 'Upload failed'));
            };
            xhr.onerror = () => rejectOnce(signal?.aborted ? uploadCancelledError() : uploadNetworkError());
            xhr.ontimeout = () => rejectOnce(new ApiError('Upload timed out', 0, 'upload_timeout'));
            xhr.onabort = () => rejectOnce(uploadCancelledError());

            if (signal?.aborted) {
                rejectOnce(uploadCancelledError());
                return;
            }
            signal?.addEventListener('abort', handleAbortSignal, { once: true });
            xhr.send(body);
        });
    }

    private async uploadSignedUrlAttempt(
        uploadUrl: string,
        file: File,
        contentType: string,
        callbacks: UploadCallbacks,
    ): Promise<void> {
        return new Promise<void>((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            const { onProgress, signal } = callbacks;
            let settled = false;

            const cleanup = () => {
                signal?.removeEventListener('abort', handleAbortSignal);
            };
            const resolveOnce = () => {
                if (settled) return;
                settled = true;
                cleanup();
                resolve();
            };
            const rejectOnce = (error: unknown) => {
                if (settled) return;
                settled = true;
                cleanup();
                reject(error);
            };
            const handleAbortSignal = () => xhr.abort();

            xhr.open('PUT', uploadUrl);
            xhr.setRequestHeader('Content-Type', contentType);
            xhr.upload.onprogress = (event) => {
                if (!onProgress || !event.lengthComputable || event.total <= 0) return;
                onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
            };
            xhr.onload = () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolveOnce();
                    return;
                }
                rejectOnce(new ApiError(
                    `Upload failed with status ${xhr.status}`,
                    xhr.status,
                    'upload_http_error',
                ));
            };
            xhr.onerror = () => rejectOnce(signal?.aborted ? uploadCancelledError() : uploadNetworkError());
            xhr.ontimeout = () => rejectOnce(new ApiError('Upload timed out', 0, 'upload_timeout'));
            xhr.onabort = () => rejectOnce(uploadCancelledError());

            if (signal?.aborted) {
                rejectOnce(uploadCancelledError());
                return;
            }
            signal?.addEventListener('abort', handleAbortSignal, { once: true });
            xhr.send(file);
        });
    }

    async login(email: string, password: string): Promise<TokenResponse> {
        const formData = new URLSearchParams();
        formData.append('username', email);
        formData.append('password', password);

        const response = await this.request<TokenResponse>('/auth/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData,
        });
        this.setToken(response.access_token);
        return response;
    }

    async register(email: string, password: string, name: string): Promise<UserResponse> {
        return this.request<UserResponse>('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ email, password, name }),
        });
    }

    async getCurrentUser(): Promise<UserResponse> {
        return this.request<UserResponse>('/auth/me');
    }

    async revokeSession(): Promise<LogoutResponse> {
        return this.request<LogoutResponse>('/auth/logout', {
            method: 'POST',
            keepalive: true,
        });
    }

    async getPointsBalance(): Promise<PointsBalanceResponse> {
        return this.request<PointsBalanceResponse>('/auth/points');
    }

    async getCreditCatalog(
        locale: ConsumerContractLocale = 'el',
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
        return this.request<CreditCheckoutResponse>('/billing/checkout', {
            method: 'POST',
            headers: { 'Idempotency-Key': idempotencyKey },
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
        );
    }

    async listBillingPurchases(): Promise<BillingPurchaseResponse[]> {
        return this.request<BillingPurchaseResponse[]>('/billing/purchases');
    }

    async listPendingBillingInvoices(
        after?: string,
        limit: number = 50,
    ): Promise<BillingAdminPendingInvoicesResponse> {
        const params = new URLSearchParams({ limit: String(limit) });
        if (after) {
            params.set('after', after);
        }
        return this.request<BillingAdminPendingInvoicesResponse>(
            `/billing/admin/invoices/pending?${params.toString()}`,
            { cache: 'no-store' },
        );
    }

    async recordIssuedAadeDocument(
        invoiceId: string,
        payload: RecordIssuedAadeDocumentPayload,
    ): Promise<RecordedAadeDocumentResponse> {
        return this.request<RecordedAadeDocumentResponse>(
            `/billing/admin/invoices/${encodeURIComponent(invoiceId)}/record-issued`,
            {
                method: 'POST',
                cache: 'no-store',
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
            params.set('after', after);
        }
        return this.request<BillingAdminPendingRefundsResponse>(
            `/billing/admin/refunds/pending?${params.toString()}`,
            { cache: 'no-store' },
        );
    }

    async recordManualRefundAccounting(
        reversalId: string,
        payload: RecordManualRefundAccountingPayload,
    ): Promise<RecordedManualRefundAccountingResponse> {
        return this.request<RecordedManualRefundAccountingResponse>(
            `/billing/admin/refunds/${encodeURIComponent(reversalId)}/record-aade-adjustment`,
            {
                method: 'POST',
                cache: 'no-store',
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
            params.set('after', after);
        }
        return this.request<BillingAdminPendingWithdrawalsResponse>(
            `/billing/admin/withdrawals/pending?${params.toString()}`,
            { cache: 'no-store' },
        );
    }

    async resolveBillingWithdrawal(
        withdrawalId: string,
        payload: ResolveBillingWithdrawalPayload,
    ): Promise<BillingWithdrawalResolutionResponse> {
        return this.request<BillingWithdrawalResolutionResponse>(
            `/billing/admin/withdrawals/${encodeURIComponent(withdrawalId)}/resolve`,
            {
                method: 'POST',
                cache: 'no-store',
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
                method: 'POST',
                headers: { 'Idempotency-Key': idempotencyKey },
                body: JSON.stringify(payload),
            },
        );
    }

    async downloadBillingArtifact(endpoint: string): Promise<Blob> {
        if (!endpoint.startsWith('/billing/purchases/')) {
            throw new Error('Invalid billing artifact path');
        }
        const headers: Record<string, string> = {};
        if (this.token) {
            headers.Authorization = `Bearer ${this.token}`;
        }
        const response = await fetch(`${API_BASE}${endpoint}`, { headers });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({
                detail: 'Billing artifact download failed',
            }));
            throw new Error(
                typeof errorData.detail === 'string'
                    ? errorData.detail
                    : 'Billing artifact download failed',
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
        const encodedMetadata = encodeUtf8Base64(JSON.stringify({
            filename: file.name,
            ...normalizedSettings,
        }));
        if (
            encodedMetadata
            && encodedMetadata.length <= STREAM_UPLOAD_METADATA_HEADER_MAX_CHARS
        ) {
            return this.uploadBody<JobResponse>(
                '/videos/process-stream',
                file,
                callbacks,
                {
                    'Content-Type': file.type || 'application/octet-stream',
                    'X-Gsubs-Upload-Metadata': encodedMetadata,
                },
            );
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('transcribe_tier', normalizedSettings.transcribe_tier);
        formData.append('transcribe_provider', normalizedSettings.transcribe_provider);
        formData.append('openai_model', normalizedSettings.openai_model);
        formData.append('video_quality', normalizedSettings.video_quality);
        formData.append('video_resolution', normalizedSettings.video_resolution);
        formData.append('use_llm', String(normalizedSettings.use_llm));
        formData.append('context_prompt', normalizedSettings.context_prompt);
        formData.append('subtitle_position', String(normalizedSettings.subtitle_position));
        formData.append('max_subtitle_lines', String(normalizedSettings.max_subtitle_lines));
        if (normalizedSettings.subtitle_color) {
            formData.append('subtitle_color', normalizedSettings.subtitle_color);
        }
        formData.append('shadow_strength', String(normalizedSettings.shadow_strength));
        formData.append('highlight_style', normalizedSettings.highlight_style);
        formData.append('subtitle_size', String(normalizedSettings.subtitle_size));
        formData.append('karaoke_enabled', String(normalizedSettings.karaoke_enabled));
        formData.append('watermark_enabled', String(normalizedSettings.watermark_enabled));

        return this.uploadBody<JobResponse>('/videos/process', formData, callbacks);
    }

    async createGcsUploadUrl(file: File): Promise<GcsUploadUrlResponse> {
        const contentType = file.type || 'application/octet-stream';
        return this.request<GcsUploadUrlResponse>('/videos/gcs/upload-url', {
            method: 'POST',
            body: JSON.stringify({
                filename: file.name,
                content_type: contentType,
                size_bytes: file.size,
            }),
        });
    }

    async uploadToSignedUrl(
        uploadUrl: string,
        file: File,
        contentType: string,
        callbacks: UploadCallbacks = {},
    ): Promise<void> {
        for (let attempt = 1; attempt <= SIGNED_UPLOAD_MAX_ATTEMPTS; attempt += 1) {
            try {
                await this.uploadSignedUrlAttempt(uploadUrl, file, contentType, callbacks);
                callbacks.onUploadComplete?.();
                return;
            } catch (error) {
                if (
                    callbacks.signal?.aborted
                    || (error instanceof ApiError && error.code === 'upload_cancelled')
                    || !isRetryableSignedUploadError(error)
                    || attempt === SIGNED_UPLOAD_MAX_ATTEMPTS
                ) {
                    throw error;
                }

                callbacks.onProgress?.(0);
                callbacks.onRetry?.(attempt + 1, SIGNED_UPLOAD_MAX_ATTEMPTS);
                await waitForUploadRetry(
                    SIGNED_UPLOAD_RETRY_BASE_DELAY_MS * (2 ** (attempt - 1)),
                    callbacks.signal,
                );
            }
        }
    }

    async processVideoFromGcs(uploadId: string, settings: {
        transcribe_tier?: string;
        transcribe_provider?: string;
        openai_model?: string;
        source_duration_seconds?: number | null;
        video_quality?: string;
        video_resolution?: string;
        use_llm?: boolean;
        context_prompt?: string;
        subtitle_position?: number;
        max_subtitle_lines?: number;
        subtitle_color?: string;
        shadow_strength?: number;
        highlight_style?: string;
        subtitle_size?: number;
        karaoke_enabled?: boolean;
        watermark_enabled?: boolean;
    }): Promise<JobResponse> {
        return this.request<JobResponse>('/videos/gcs/process', {
            method: 'POST',
            body: JSON.stringify({
                upload_id: uploadId,
                transcribe_tier: settings.transcribe_tier || 'standard',
                transcribe_provider: settings.transcribe_provider || 'mock',
                openai_model: settings.openai_model || '',
                source_duration_seconds: settings.source_duration_seconds ?? null,
                video_quality: settings.video_quality || 'balanced',
                video_resolution: settings.video_resolution || '',
                use_llm: Boolean(settings.use_llm),
                context_prompt: settings.context_prompt || '',
                subtitle_position: settings.subtitle_position ?? 16,
                max_subtitle_lines: settings.max_subtitle_lines ?? 2,
                subtitle_color: settings.subtitle_color ?? null,
                shadow_strength: settings.shadow_strength ?? 4,
                highlight_style: settings.highlight_style || 'karaoke',
                subtitle_size: settings.subtitle_size ?? 100,
                karaoke_enabled: settings.karaoke_enabled ?? true,
                watermark_enabled: settings.watermark_enabled ?? false,
            }),
        });
    }

    async getJobStatus(jobId: string): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}`);
    }

    async getJobs(): Promise<JobResponse[]> {
        return this.request<JobResponse[]>('/videos/jobs');
    }

    async getJobsPaginated(page: number = 1, pageSize: number = 5): Promise<PaginatedJobsResponse> {
        return this.request<PaginatedJobsResponse>(`/videos/jobs/paginated?page=${page}&page_size=${pageSize}`);
    }



    async updateProfile(name: string): Promise<UserResponse> {
        return this.request<UserResponse>('/auth/me', {
            method: 'PUT',
            body: JSON.stringify({ name }),
        });
    }

    async updatePassword(password: string, confirm_password: string): Promise<{ status: string }> {
        return this.request('/auth/password', {
            method: 'PUT',
            body: JSON.stringify({ password, confirm_password }),
        });
    }

    async getHistory(limit: number = 50): Promise<HistoryEvent[]> {
        return this.request<HistoryEvent[]>(`/history/?limit=${limit}`);
    }

    async getTikTokAuthUrl(): Promise<{ auth_url: string; state: string }> {
        return this.request('/tiktok/url');
    }

    async tiktokCallback(code: string, state: string): Promise<{ access_token: string }> {
        return this.request('/tiktok/callback', {
            method: 'POST',
            body: JSON.stringify({ code, state }),
        });
    }

    async uploadToTikTok(access_token: string, video_path: string, title: string, description: string): Promise<unknown> {
        return this.request('/tiktok/upload', {
            method: 'POST',
            body: JSON.stringify({ access_token, video_path, title, description }),
        });
    }

    async getGoogleAuthNonce(): Promise<{
        nonce: string;
        expires_in: number;
        client_id: string;
    }> {
        return this.request('/auth/google/nonce', {
            credentials: 'include',
        });
    }

    async googleLogin(idToken: string): Promise<TokenResponse> {
        const response = await this.request<TokenResponse>('/auth/google', {
            method: 'POST',
            credentials: 'include',
            body: JSON.stringify({ id_token: idToken }),
        });
        this.setToken(response.access_token);
        return response;
    }

    async exportData(): Promise<ExportDataResponse> {
        return this.request<ExportDataResponse>('/auth/export');
    }

    async deleteAccount(): Promise<{ status: string; message: string }> {
        const response = await this.request<{ status: string; message: string }>('/auth/me', {
            method: 'DELETE',
        });
        this.clearToken();
        return response;
    }

    async deleteJob(jobId: string): Promise<{ status: string; job_id: string }> {
        return this.request<{ status: string; job_id: string }>(`/videos/jobs/${jobId}`, {
            method: 'DELETE',
        });
    }

    async deleteJobs(jobIds: string[]): Promise<{ status: string; deleted_count: number }> {
        return this.request<{ status: string; deleted_count: number }>('/videos/jobs/batch-delete', {
            method: 'POST',
            body: JSON.stringify({ job_ids: jobIds }),
        });
    }

    async cancelJob(jobId: string): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}/cancel`, {
            method: 'POST',
        });
    }

    async exportVideo(jobId: string, resolution: string, settings?: {
        subtitle_position?: number;
        max_subtitle_lines?: number;
        subtitle_color?: string;
        shadow_strength?: number;
        highlight_style?: string;
        subtitle_size?: number;
        karaoke_enabled?: boolean;
        watermark_enabled?: boolean;
    }): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}/export`, {
            method: 'POST',
            body: JSON.stringify({ resolution, ...settings }),
        });
    }

    async reprocessJob(jobId: string, settings: {
        transcribe_tier?: string;
        transcribe_provider?: string;
        openai_model?: string;
        video_quality?: string;
        video_resolution?: string;
        use_llm?: boolean;
        context_prompt?: string;
        subtitle_position?: number;
        max_subtitle_lines?: number;
        subtitle_color?: string | null;
        shadow_strength?: number;
        highlight_style?: string;
        subtitle_size?: number;
        karaoke_enabled?: boolean;
        watermark_enabled?: boolean;
    }): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}/reprocess`, {
            method: 'POST',
            body: JSON.stringify({
                transcribe_tier: settings.transcribe_tier || 'standard',
                transcribe_provider: settings.transcribe_provider || 'mock',
                openai_model: settings.openai_model || '',
                video_quality: settings.video_quality || 'balanced',
                video_resolution: settings.video_resolution || '',
                use_llm: Boolean(settings.use_llm),
                context_prompt: settings.context_prompt || '',
                subtitle_position: settings.subtitle_position ?? 16,
                max_subtitle_lines: settings.max_subtitle_lines ?? 2,
                subtitle_color: settings.subtitle_color ?? null,
                shadow_strength: settings.shadow_strength ?? 4,
                highlight_style: settings.highlight_style || 'karaoke',
                subtitle_size: settings.subtitle_size ?? 100,
                karaoke_enabled: settings.karaoke_enabled ?? true,
                watermark_enabled: settings.watermark_enabled ?? false,
            }),
        });
    }

    async updateJobTranscription(jobId: string, cues: TranscriptionCue[]): Promise<{ status: string }> {
        return this.request<{ status: string }>(`/videos/jobs/${jobId}/transcription`, {
            method: 'PUT',
            body: JSON.stringify({ cues }),
        });
    }



    async factCheck(jobId: string): Promise<FactCheckResponse> {
        return this.request<FactCheckResponse>(`/videos/jobs/${jobId}/fact-check`, {
            method: 'POST',
        });
    }

    async socialCopy(jobId: string): Promise<SocialCopyResponse> {
        return this.request<SocialCopyResponse>(`/videos/jobs/${jobId}/social-copy`, {
            method: 'POST',
        });
    }
}

interface FactCheckItem {
    mistake_el: string;
    mistake_en: string;
    correction_el: string;
    correction_en: string;
    explanation_el: string;
    explanation_en: string;
    severity: 'minor' | 'medium' | 'major';
    confidence: number;
    real_life_example_el: string;
    real_life_example_en: string;
    scientific_evidence_el: string;
    scientific_evidence_en: string;
}

export interface FactCheckResponse {
    items: FactCheckItem[];
    truth_score: number;
    supported_claims_pct: number;
    claims_checked: number;
    balance?: number | null;
}

interface SocialCopySchema {
    title_el: string;
    title_en: string;
    description_el: string;
    description_en: string;
    hashtags: string[];
}

export interface SocialCopyResponse {
    social_copy: SocialCopySchema;
    balance?: number | null;
}

export const api = new ApiClient();
