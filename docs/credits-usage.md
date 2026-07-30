# Prepaid video credits and Stripe handoff

Updated: 2026-07-30

Stripe test-mode setup and a card Checkout have been validated. Production
paid credits remain fail closed until the separate live infrastructure and
verification are complete and an authorized operator explicitly enables them.
No subscription or automatic renewal is used.

## Customer prices

The backend is the pricing authority. The provider/model selected internally
does not change the visible price of a video.

| Server-measured duration | Credits |
| --- | ---: |
| `0:01` through `3:00` | 30 |
| `3:00.001` through `6:00` | 60 |
| `6:00.001` through `10:00` | 100 |

An upload with an unreadable duration is rejected. A direct upload is probed
before reservation. A GCS upload, whose browser-reported duration is not
trusted, reserves 100 credits and refunds the difference after the server
measures the file. More than 10 minutes is rejected.

The immutable package catalog is:

| Package | Gross price | Credits | Maximum 10-minute videos |
| --- | ---: | ---: | ---: |
| Starter | €1.00 | 100 | 1 |
| Creator (`core`) | €3.00 | 350 | 3, plus 50 credits |
| Studio (`pro`) | €10.00 | 1,200 | 12 |

New accounts start with zero credits; GSUBS does not grant signup, trial or
email-verification credits automatically. Purchased and any legacy or explicit
non-paid credits remain separate in the ledger. Any request that can spend
money at an external provider requires purchased credits; non-paid credits can
fund only local/mock work. A refund or dispute claws back unused paid credits
and records debt for credits already consumed. A later purchase repays that
debt before becoming spendable.

## Conservative unit economics

These figures are a planning model, not tax advice. They assume:

- Greek B2C price inclusive of 24% VAT;
- a standard EEA card at 1.5% + €0.25;
- the current Scribe v2 API list price of US$0.22/hour;
- an optional bundled social-copy call at the full configured GPT-5 mini
  limits (3,750 input and 3,000 output tokens at US$0.25/US$2.00 per million);
- conservative USD/EUR parity; and
- no refund of the original Stripe processing fee.

The maximum modeled external-provider cost for one 10-minute video is about
€0.044. The table allocates the one package payment fee across the number of
100-credit videos it funds:

| Package | Ex-VAT revenue per 100 credits | Allocated Stripe fee | Provider ceiling | Contribution | Margin on ex-VAT revenue |
| --- | ---: | ---: | ---: | ---: | ---: |
| Starter | €0.806 | €0.265 | €0.044 | €0.498 | 61.7% |
| Core | €0.691 | €0.084 | €0.044 | €0.563 | 81.5% |
| Pro | €0.672 | €0.033 | €0.044 | €0.595 | 88.6% |

Even after an additional provisional €0.10/video allowance for compute,
storage and egress, the modeled margins are approximately 49.3%, 67.0% and
73.7%. Production telemetry must replace that allowance before claiming a
guaranteed margin. A €0.50 single-video payment is mathematically positive but
leaves almost no margin after that infrastructure allowance; €1.00 is the
practical minimum. The €20 Stripe dispute fee is an exceptional risk that no
per-video price this small can absorb, so dispute monitoring remains a launch
requirement.

Current official references:

- [Stripe pricing for Greece](https://stripe.com/en-gr/pricing)
- [ElevenLabs API pricing](https://elevenlabs.io/pricing/api?price.section=speech_to_text)
- [Groq on-demand pricing](https://groq.com/pricing)
- [OpenAI GPT-5 mini model pricing](https://developers.openai.com/api/docs/models/gpt-5-mini)

## Money and provider safety invariants

1. Checkout uses server-owned fixed Stripe Price IDs. The browser never sends
   an amount or number of credits.
2. Each checkout request has a client idempotency key and an immutable database
   snapshot. The Stripe SDK also receives a server-derived idempotency key.
3. The browser follows only the exact `https://checkout.stripe.com` origin.
4. Checkout uses Stripe's dynamic payment-method eligibility and creates a
   manual-capture PaymentIntent. The selected eligible method is authorized
   first; capture occurs only after the signed event proves a Greek billing
   address and the exact session, PaymentIntent, amount, currency, user,
   package, credit, catalog and consumer-contract metadata. An ineligible
   authorization is canceled and grants no credits.
5. Credits are granted only after the captured PaymentIntent reports
   `succeeded` with the exact received amount. A provider capture can be replayed
   safely after a local transaction failure and cannot grant twice.
6. The signed webhook's session ID, PaymentIntent, amount, currency, user,
   package, credits and catalog metadata must match the stored snapshot.
7. Stripe event IDs are receipt-hashed and serialized with a PostgreSQL
   advisory lock. Duplicate or conflicting payloads cannot grant twice.
8. Every fulfillment, expiry, refund and dispute event affecting the same
   purchase is serialized under a second purchase lock. A PaymentIntent is
   database-unique, and refund/dispute wallet mutations remain event-idempotent,
   including reinstate-then-lost transitions.
9. A provider call reserves paid credits plus daily/monthly USD budget before
   dispatch. Zero budgets mean closed.
10. Provider estimates reserve 25% headroom. Paid calls use zero SDK retries and
   bounded output tokens. Once a call is marked dispatched, a network failure
   cannot trigger another paid attempt or a credit refund.
11. The visible 30/60/100 video charge includes optional social-copy generation;
   it is not deducted a second time.

## Validated accounting baseline and remaining consumer handoff

The accountant-reviewed MizAI workflow is the GSUBS accounting baseline:

- Starter €1, Creator €3 and Studio €10 are final gross prices inclusive of
  24% VAT for the accountant-reviewed Greek B2C baseline. Stripe Automatic Tax
  remains disabled. This baseline does not approve sales to every billing
  country that Stripe Checkout can collect.
- In the tested sandbox, Checkout is hosted by Stripe and collects the buyer's
  individual name, email and billing address. Stripe handles card details;
  GSUBS never stores the full card number or CVC. This does not describe an
  active public sale.
- The Stripe receipt is payment evidence, not an AADE tax document. Ascentia
  issues the tax document manually through e-Timologio and records its series,
  number and MARK against the internal purchase.
- Credits are prepaid internal units used only to pay for GSUBS digital
  processing; they are not, by themselves, downloadable digital content. The
  final consumer-law classification, withdrawal wording and proportional
  refund treatment remain subject to legal review. The application must not
  publish a blanket “used credits are non-refundable” rule or infer that
  crediting the wallet alone ends a mandatory withdrawal right.
- Media workspaces still expire after 24 hours. The minimum payment, invoice
  and MARK snapshot is retained through the end of the fifth full year after
  the relevant tax year, and longer only when required by law or an active tax
  or payment dispute.

The sandbox has one `GSUBS Credits` Product, three one-time EUR Prices, a
least-privilege restricted test key and a successful €1 card Checkout with a
signed webhook and exactly one 100-credit fulfillment. This proves test mode;
it does not configure or authorize live sales.

The payment reconciliation, durable original-document snapshot, consumer
contract evidence and retention foundation is implemented in this release
candidate. Consumer-contract wording and delivery are deliberately marked
draft/unapproved in code. The public Terms page says paid-credit sales are not
active and does not publish the draft sale/withdrawal text as operative terms;
the unauthenticated catalog returns `consumer_contract: null` until the full
backend approval manifest matches. The approval predicate also rejects any
policy, terms, withdrawal, confirmation-template or disclosure identifier that
still contains `draft`; status and manifest flips cannot approve draft
versions.
The separate AADE adjustment-document workflow for refunds, disputes and
chargebacks remains a live-activation blocker. None of this is production
evidence until the full gates pass and the exact clean commit is deployed and
verified on `gsubs.gr`.

Before enabling live paid Checkout:

1. Deploy and verify the completed order-independent refund/dispute
   reconciliation and its reverse-delivery regression suite on `gsubs.gr`,
   while the tracked production Compose keeps Checkout disabled.
2. Apply and verify the billing migrations through
   `0018_approved_contract_delivery` while Checkout remains disabled. Confirm
   account deletion preserves only legally required financial evidence, still
   removes the 24-hour media workspace, and cannot orphan a pending withdrawal
   acknowledgement. Migration 0018 preserves legacy pending confirmations and
   adds schema support for the exact `available_approved` account-vault
   identity; it does not rewrite old evidence or approve the current draft
   channel by itself.
3. Obtain an accountant-approved billing-country policy for the 24% VAT
   baseline. Enforce the permitted geography before creating a charge and
   verify the signed Checkout billing country again before fulfillment. A
   populated country field alone is not tax readiness; any mismatch or
   unapproved country must fail closed without granting credits.
4. Confirm with the accountant how every refund, dispute and chargeback is
   represented in AADE. Add the reviewed one-to-many adjustment workflow so
   each required correction has its own immutable identity and MARK, without
   mutating the original document. AADE supports associated retail credit
   documents (11.4), but the application must not infer that every Stripe
   reversal requires that treatment:
   [official AADE update](https://aade.gr/teleytaia-nea-mydata/timologio-update-ekdosi-syshetizomenon-pistotikon-lianikis-114).
5. Obtain consumer-law review of the exact localized disclosures, complete
   model withdrawal form, full legal trader identity, geographical address and
   telephone number. Approve a real durable delivery channel for both the
   contract confirmation and withdrawal acknowledgement, plus an account
   deletion design that preserves access during the applicable period. Bind the
   exact EL/EN disclosure IDs, policy/terms/withdrawal/template versions and
   canonical SHA-256 values in the code-owned backend approval manifest, and
   separately review the byte-identical backend/frontend
   `paid_credit_legal_publication.json` identity. Its non-draft Terms version
   and digest must bind `/terms` to that exact backend manifest; the current
   inactive identity has a null digest, so backend activation and frontend
   publication both remain impossible. Do not approve that identity until the
   frontend actually publishes the complete counsel-approved localized
   paid-credit sale terms at `/terms`, a real `id="withdrawal"` section
   containing the complete localized model withdrawal form, and reviewed
   conditional Privacy wording for the Stripe/payment/accounting processing
   that becomes active with paid sales. Browser tests must prove the approved
   `/terms#withdrawal` deep link resolves to that real content in both locales;
   an approval JSON/status change by itself is not publication.
6. Verify the implemented append-only withdrawal decision/outcome workflow
   against the accountant-approved process. It binds any Stripe refund and
   AADE adjustment/MARK without mutating the original request or original
   tax-document evidence and releases the retention hold only after a terminal
   reviewed outcome. `ADJUSTMENT_WORKFLOW_IMPLEMENTED = True` records technical
   capability only; the independent approval status must remain pending until
   the accountant process and durable customer notification are verified.
7. Implement and have counsel review an explicit Europe/Athens legal calendar,
   including exclusion of the contract-conclusion day and any applicable
   weekend or Greek public-holiday extension. Until then the application must
   not calculate or publish a 14-day deadline or eligibility boolean. It keeps
   the online action available for every concluded contract without an
   existing request, timestamps every request and records only
   `timeliness_assessment_status = pending_manual_review`.
8. Confirm the deployed database contains no historical fulfilled live Stripe
   purchase requiring an adjustment before relying on the disabled foundation.
9. Create separate live Prices and a least-privilege live restricted key. It
   must grant Checkout Sessions Write, PaymentIntents Write and Refunds Read;
   PaymentIntents Write is required for manual capture and cancellation after
   the Greece-only signed billing-address check;
   Refunds Read is required for authoritative, fully paginated reconciliation
   before any refund-driven wallet mutation. Store the key only in the
   production secret store. Treat a permission error, incomplete page or
   provider error as an activation blocker.
10. Prepare a separate reviewed Compose/verifier release that can receive live
   secrets while `GSP_PAID_CREDITS_ENABLED=0`. Add
   `https://gsubs.gr/billing/webhook`, store its live `whsec_...` secret, and
   subscribe to:
   `checkout.session.completed`,
   `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, `checkout.session.expired`,
   `charge.refunded`, `refund.created`, `refund.updated`, `refund.failed`,
   `charge.dispute.created`, `charge.dispute.updated`,
   `charge.dispute.funds_withdrawn`, `charge.dispute.funds_reinstated`, and
   `charge.dispute.closed`.
11. Verify the live Stripe seller identity, statement descriptor, support
   contact and receipt settings match the published GSUBS terms.
12. Replace the stale template legal pages currently published on the
    Ascentia site before using them as the trader's official legal destination:
    [privacy](https://ascentia-gp.com/privacy) and
    [terms](https://ascentia-gp.com/terms).
13. Only with explicit authorization for a real charge, enable
   `GSP_PAID_CREDITS_ENABLED=1` in that reviewed deployment contract, run one
   smallest-package Checkout and reconcile Stripe total, `credit_purchases`,
   `stripe_webhook_events`, point transactions and the manual AADE record.
   Verify that MARK remains empty until the tax document is actually issued.
14. Keep paid Checkout enabled only after the deployed endpoint, migrations,
   signed webhook, duplicate delivery and end-to-end reconciliation evidence
   are all green; otherwise return it to `0`. Activation is one atomic reviewed
   release: backend EL/EN manifest and implementation booleans, frontend legal
   publication gate, future durable-delivery/resolution schema, three environment
   approval flags, Stripe secrets/Prices/webhook, and production verifier must
   agree in the same deployed version.

The current Hetzner Compose file hard-forces paid Checkout and Automatic Tax
off, hard-forces every consumer-contract/confirmation/adjustment approval to
off, and keeps the billing-admin allowlist empty. It permits only an
all-or-nothing Stripe staging bundle from the untracked production environment
and routes the SDK through a method/path-scoped internal relay. A partial bundle
fails verification, and editing `.env.production` alone still cannot enable or
approve live sales or the AADE-admin capability. Actual activation requires a
separate reviewed commit changing both
`deploy/hetzner/docker-compose.production.yml` and its corresponding
`verify-production.sh` assertions.

## Current sandbox mapping

This mapping is test-only and does not enable production sales or issue an
AADE document:

| GSUBS package | Credits | Gross amount | Stripe test Price |
| --- | ---: | ---: | --- |
| Starter | 100 | €1.00 | `price_1TxBTrFxotLWYrtgK2OtxFsN` |
| Creator (`core`) | 350 | €3.00 | `price_1TxBTrFxotLWYrtgnB0Aq7Hp` |
| Studio (`pro`) | 1,200 | €10.00 | `price_1TxBTrFxotLWYrtg7Hh8VEyR` |

All three Prices belong to the Stripe sandbox Product
`prod_Ux5fP4UP201f4y` (`GSUBS Credits`), which uses the accountant-approved
MizAI SaaS business-use tax code `txcd_10103001`. For manual e-Timologio
reconciliation, use the existing AADE service item with code `4`. The live
MizAI Greek-retail precedent verified in e-Timologio on 2026-07-26 is an
`11.2 - ΑΠΥ` in series `0`, paid through the domestic professional payment
account method, in EUR, with one service line and 24% VAT included in the gross
price; it has no discount, withholding or other fee. GSUBS fixes the same
document type and series for this Greek B2C flow, while using item `4 - GSUBS
Credits` instead of item `2 - MizAI Credits`. Match one paid Stripe Checkout
to one internal `credit_purchases` row by
`checkout_session_id`, `payment_intent_id`, `purchase_id` and
`integration_identifier`; then issue the appropriate AADE document manually.
After real issuance, an authorized administrator may record the document
type, series, AA, MARK and issue time exactly once through
`POST /billing/admin/invoices/{invoice_id}/record-issued`. That endpoint only
records an already-issued document; it never calls AADE or Stripe. The
integration must never infer that a Stripe payment already has a MARK.

## Live activation blockers

Keep production Checkout disabled until all of these are closed:

- the accountant approves the exact billing-country scope for the 24% VAT
  model, and the application enforces that scope before Checkout plus verifies
  the signed billing country again before fulfillment;
- the completed order-independent dispute/refund reconciliation and
  reverse-delivery regression suite pass against the deployed release;
- the accountant confirms the exact AADE treatment of refunds, disputes and
  chargebacks, and the application can queue and retain every required
  adjustment or credit document with its own immutable identity and MARK;
- a consumer-law reviewer approves the complete localized sale/withdrawal
  terms, model form, full trader identity/address/telephone, durable delivery
  channel and account-deletion behavior, and the exact EL/EN manifest plus
  the byte-identical backend/frontend public-Terms approval identity and digest
  are one reviewed code change;
- the approved frontend actually renders those digest-bound localized
  paid-credit terms at `/terms`, a real `#withdrawal` section with the complete
  model form, and matching conditional Stripe/payment/accounting wording on
  `/privacy`; browser tests verify both locales and the deep link before the
  publication identity can become approved;
- the pending-only withdrawal placeholder has an append-only terminal outcome
  linked to any Stripe refund and accountant-approved AADE adjustment, so its
  retention hold is bounded after resolution, durable notification is recorded,
  and `ADJUSTMENT_WORKFLOW_IMPLEMENTED` can truthfully become `True`;
- the reviewed Europe/Athens legal calendar and Greek holiday rules replace
  manual timeliness assessment; until then no computed deadline or
  in-window/out-of-window claim is exposed and the online action remains
  available for every concluded contract that has no existing request;
- all billing migrations through `0018_approved_contract_delivery`,
  fiscal-year retention behavior and the account-deletion exceptions pass
  deployed verification; migration 0018 provides the approved delivery schema
  capability but does not constitute legal or operational approval;
- the external Ascentia privacy and terms pages no longer contain stale
  third-party template names or support contacts;
- the reviewed Stage 1 deployment safely stages the complete Stripe bundle
  while preserving every fail-closed activation gate, followed by a separate
  reviewed activation change; live activation is never an environment-only
  change;
- separate live Prices, a least-privilege live restricted key with Checkout
  Sessions Write, PaymentIntents Write and Refunds Read, and a signed live
  webhook endpoint pass the complete reconciliation checklist, including a
  successful fully paginated Refund list probe;
- one explicitly authorized live Starter transaction is reconciled end to end,
  while the AADE MARK remains manual and is never inferred from Stripe.

Required environment shape (secrets must not be committed):

```dotenv
GSP_PAID_CREDITS_ENABLED=0
GSP_CONSUMER_POLICY_APPROVED=0
GSP_DURABLE_CONFIRMATION_CHANNEL_READY=0
GSP_ADJUSTMENT_WORKFLOW_READY=0
GSP_STRIPE_API_BASE=http://edge:8081/stripe
GSP_STRIPE_RESTRICTED_KEY=
GSP_STRIPE_WEBHOOK_SECRET=
GSP_STRIPE_PRICE_STARTER=
GSP_STRIPE_PRICE_CORE=
GSP_STRIPE_PRICE_PRO=
GSP_STRIPE_SUCCESS_URL=https://gsubs.gr/?checkout=success&session_id={CHECKOUT_SESSION_ID}
GSP_STRIPE_CANCEL_URL=https://gsubs.gr/?checkout=cancelled
GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0
GSP_BILLING_ADMIN_USER_IDS=

GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0
GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=0
GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0
GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER=1.25
```

With `GSP_PAID_CREDITS_ENABLED=1`, startup rejects a missing/ordinary Stripe
key, missing webhook secret, missing Price ID, unsafe production return URL or
Automatic Tax enabled against the approved manual tax workflow. Provider
budgets should remain zero until real provider activation is approved
separately.

`GSP_BILLING_ADMIN_USER_IDS` accepts a comma-separated allowlist of immutable
internal `users.id` values. Email addresses, malformed entries, duplicates and
unverified accounts are rejected fail closed. Leaving it empty disables the
manual billing-admin endpoints.

The protected reconciliation screen is `/admin/billing`. It only records the
identity of a document that has already been issued finally in AADE
e-Timologio; it never issues a document and never writes to Stripe or AADE.
Recording is allowed only during the first 15 minutes of a freshly issued
admin session. If that window expires, sign out, sign in again with the
allowlisted account, refresh the queue, and re-check the final document before
submitting.

## Operational verification

```bash
# Canonical release gates, from the repository root
make ci
(cd frontend && npm run build)

# Focused billing regression suite for iteration
python3 -m pytest --no-cov backend/tests/services/test_billing.py \
  backend/tests/services/test_consumer_contracts.py \
  backend/tests/services/test_billing_snapshots.py \
  backend/tests/services/test_points.py \
  backend/tests/services/test_financial_records.py \
  backend/tests/services/test_provider_budget.py \
  backend/tests/services/test_usage_ledger.py \
  backend/tests/services/test_charge_plans.py \
  backend/tests/test_billing_admin_api.py \
  backend/tests/test_billing_financial_migration.py \
  backend/tests/test_consumer_contract_migration.py \
  backend/tests/test_billing_financial_retention.py \
  backend/tests/test_billing_endpoints.py -q
```

`make ci` (and its `make check-all` alias) creates a disposable PostgreSQL
database, then runs the repository contract, strict static analysis, backend
and frontend coverage suites, integration and real-media export tests,
architecture and Java 25 checks, dependency/security audits, and Playwright
E2E. The database is dropped after success or failure, so stale local fixtures
cannot change the result. The Playwright gate builds and serves the production
Next.js bundle so browser checks cannot be disrupted by development-server HMR.

Migrations `0008_video_credits_and_billing` through
`0018_approved_contract_delivery` are required for this disabled scaffold.
Migration 0018 can represent both legacy pending and future approved durable
delivery without mutating historical evidence. Live activation still requires
the independently approved EL/EN manifest, legal publication identity,
accounting workflow, Stripe dashboard verification and tracked deployment
gates; applying the migration alone cannot open Checkout.
