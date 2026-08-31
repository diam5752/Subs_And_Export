import { fireEvent, screen } from "@testing-library/react";

export const mockPaidCreditLegalPublication = { approved: true };
export const mockLocaleState = { locale: "el" as "el" | "en" };
const originalPaidCreditUiReview =
  process.env.NEXT_PUBLIC_PAID_CREDITS_UI_REVIEW;

export const consumerContract = {
  schema_version: 1,
  status: "approved",
  classification: "digital_service_with_prepaid_internal_units",
  disclosure_id: "gsubs-b2c-el-v1",
  disclosure_sha256: "a".repeat(64),
  locale: "el" as const,
  policy_version: "policy-v1",
  terms_version: "terms-v1",
  withdrawal_notice_version: "withdrawal-v1",
  confirmation_template_version: "confirmation-v1",
  terms_url: "/terms",
  withdrawal_url: "/account/billing",
  model_withdrawal_form_url: "/terms#withdrawal",
  trader: {
    legal_name: "Ascentia G.P.",
    legal_form: "General Partnership (O.E.)",
    trading_name: "Ascentia",
    service: "GSUBS",
    tax_identification_number: "802523620",
    vat_id: "EL802523620",
    commercial_register: "General Commercial Registry (GEMI)",
    commercial_registration_number: "177974203000",
    euid: "ELGEMI.177974203000",
    address_line_1: "Agias Varvaras 4",
    postal_code: "16452",
    city: "Argiroupoli, Athens",
    country: "GR" as const,
    support_email: "info@ascentia-gp.com",
    support_phone: "+30 698 756 4060",
    website: "https://ascentia-gp.com/",
  },
  content: {
    title: "Consumer contract",
    service_description: "Digital processing service.",
    credit_description: "Prepaid internal units.",
    purchase_terms: "One-off purchase.",
    delivery_timing: "Credits after confirmed payment.",
    validity_and_transfer: "No automatic expiry or transfer mechanism.",
    functionality: "Processing consumes credits.",
    compatibility: "Supported browser required.",
    withdrawal_notice: "Fourteen-day withdrawal notice.",
    manual_review_notice: "Pending manual review.",
  },
  required_acceptances: {
    terms: "Accept the terms and pre-contract information.",
    immediate_performance: "Request immediate performance.",
    withdrawal_consequences: "Acknowledge the withdrawal consequences.",
  },
};

export const catalog = {
  catalog_version: "video-credits-v1",
  currency: "eur",
  billing_country_scope: ["GR"] as Array<"GR">,
  checkout_enabled: true,
  consumer_contract_status: "approved" as const,
  consumer_contract: consumerContract,
  packages: [
    { key: "starter", credits: 100, amount_eur_cents: 100, featured: false },
    { key: "creator", credits: 350, amount_eur_cents: 300, featured: true },
    { key: "studio", credits: 1200, amount_eur_cents: 1000, featured: false },
  ],
  video_pricing: [
    { key: "up_to_3m", max_duration_seconds: 180, credits: 30 },
    { key: "up_to_6m", max_duration_seconds: 360, credits: 60 },
    { key: "up_to_10m", max_duration_seconds: 600, credits: 100 },
  ],
};

interface MockCreditApi {
  getCreditCatalog: unknown;
  createCreditCheckout: unknown;
}

export function resetCreditPurchaseDialogMocks(api: MockCreditApi): void {
  jest.clearAllMocks();
  delete process.env.NEXT_PUBLIC_PAID_CREDITS_UI_REVIEW;
  mockPaidCreditLegalPublication.approved = true;
  mockLocaleState.locale = "el";
  (api.getCreditCatalog as jest.Mock).mockResolvedValue(catalog);
  (api.createCreditCheckout as jest.Mock).mockResolvedValue({
    purchase_id: "purchase-1",
    checkout_session_id: "cs_test_123",
    checkout_url: "https://checkout.stripe.com/c/pay/cs_test_123",
    status: "pending",
  });
}

export function restorePaidCreditUiReview(): void {
  if (originalPaidCreditUiReview === undefined) {
    delete process.env.NEXT_PUBLIC_PAID_CREDITS_UI_REVIEW;
  } else {
    process.env.NEXT_PUBLIC_PAID_CREDITS_UI_REVIEW = originalPaidCreditUiReview;
  }
}

export function acceptConsumerTerms(): void {
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "creditPurchaseConsentRequest",
    }),
  );
}

export function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}
