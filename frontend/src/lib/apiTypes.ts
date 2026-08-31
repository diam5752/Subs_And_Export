export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  name: string;
  beta_credits_awarded?: number;
}

export interface JobResultData {
  video_path: string;
  artifacts_dir: string;
  public_url?: string;
  artifact_url?: string;
  transcription_url?: string;
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

export interface ArtifactDownloadGrantResponse {
  download_url: string;
  expires_in: number;
}

export interface HistoryEvent {
  ts: string;
  user_id: string;
  email: string;
  kind: string;
  summary: string;
  data: Record<string, unknown>;
}

export interface UserResponse {
  id: string;
  email: string;
  name: string;
  provider: string;
  avatar_url: string | null;
}

export interface LogoutResponse {
  status: "success";
}

export interface PointsBalanceResponse {
  balance: number;
  paid_balance: number;
  promotional_balance: number;
  reversal_debt: number;
  ai_spendable_balance: number;
}

export type ProductFeedbackCategory = "idea" | "bug" | "complaint" | "chat";

export interface ProductFeedbackPayload {
  category: ProductFeedbackCategory;
  message: string;
  source_path: string;
  page_title: string;
  form_started_at: number;
  website: string;
}

export interface ProductFeedbackResponse {
  status: "received";
  id: string | null;
}

export interface CreditPackage {
  key: string;
  credits: number;
  amount_eur_cents: number;
  featured: boolean;
}

export type ConsumerContractLocale = "el" | "en";
export type BillingCountry = "GR";

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
    legal_name: string;
    legal_form: string;
    trading_name: string;
    service: string;
    tax_identification_number: string;
    vat_id: string;
    commercial_register: string;
    commercial_registration_number: string;
    euid: string;
    address_line_1: string;
    postal_code: string;
    city: string;
    country: BillingCountry;
    support_email: string;
    support_phone: string;
    website: string;
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

export interface ConsumerContractAcceptanceRequest {
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
  consumer_contract_status: "approved" | "unavailable_unapproved";
  consumer_contract: ConsumerContractDisclosure | null;
  packages: CreditPackage[];
  video_pricing: VideoCreditBracket[];
}

export interface CreditCheckoutResponse {
  purchase_id: string;
  checkout_session_id: string | null;
  checkout_url: string | null;
  status: string;
}

export interface CreditCheckoutStatusResponse {
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

export interface BillingAdminPendingInvoicesResponse {
  items: BillingAdminPendingInvoice[];
  count: number;
  next_cursor: string | null;
}

export interface RecordIssuedAadeDocumentPayload {
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

export interface BillingAdminPendingRefundsResponse {
  items: BillingAdminPendingRefund[];
  count: number;
  next_cursor: string | null;
}

export interface RecordManualRefundAccountingPayload {
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

export interface BillingAdminPendingWithdrawalsResponse {
  items: BillingAdminPendingWithdrawal[];
  count: number;
  next_cursor: string | null;
}

export type BillingWithdrawalResolutionDecision =
  "accepted_refunded" | "rejected";

export interface ResolveBillingWithdrawalPayload {
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

export interface BillingWithdrawalResponse {
  withdrawal_id: string;
  purchase_id: string;
  status: string;
  submitted_at: number;
  timeliness_assessment_status: "pending_manual_review";
  acknowledgement_sha256: string;
  acknowledgement_url: string;
}

export interface ExportDataResponse {
  profile: UserResponse;
  jobs: JobResponse[];
  history: HistoryEvent[];
  billing_purchases: Record<string, unknown>[];
  wallet: Record<string, unknown> | null;
  point_transactions: Record<string, unknown>[];
  usage_ledger: Record<string, unknown>[];
  token_usage: Record<string, unknown>[];
  provider_budget_reservations: Record<string, unknown>[];
  sessions: Record<string, unknown>[];
  oauth_states: Record<string, unknown>[];
  product_feedback: Record<string, unknown>[];
}

export interface PaginatedJobsResponse {
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
