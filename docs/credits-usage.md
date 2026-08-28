# Prepaid video credits and Stripe handoff

Updated: 2026-08-28

Stripe test-mode Checkout and the complete live production configuration have
been validated. Production paid credits are enabled only by the reviewed,
content-addressed release contract. No subscription or automatic renewal is
used.

## Customer prices

The backend is the pricing authority. The provider/model selected internally
does not change the visible price of a video.

| Server-measured duration | Credits |
| --- | ---: |
| `0:01` through `3:00` | 25 |
| `3:00.001` through `6:00` | 60 |
| `6:00.001` through `10:00` | 100 |

An upload with an unreadable duration is rejected. Every local upload is probed
by the server before reservation; browser-reported duration is never trusted.
More than 10 minutes is rejected.

The immutable package catalog is:

| Package | Gross price | Credits | Maximum 10-minute videos |
| --- | ---: | ---: | ---: |
| Starter | €1.00 | 100 | 1 |
| Creator (`core`) | €3.00 | 350 | 3, plus 50 credits |
| Studio (`pro`) | €10.00 | 1,200 | 12 |

New accounts start with zero credits; GSUBS does not grant signup, trial or
email-verification credits automatically. When the explicitly configured Beta
login campaign is enabled, the first 50 distinct users to complete a real login
receive 30 operator-sponsored, cloud-spendable credits once. Migration 0025
extends the original 20-slot campaign in place, so existing recipients keep
their ordinal and cannot claim again. Purchased, operator-sponsored and
ordinary non-paid credits remain auditable by ledger reason. External-provider
work requires purchased or operator-sponsored cloud-spendable credits;
ordinary non-paid credits can fund only local/mock work. A refund or dispute
claws back unused paid credits and records debt for credits already consumed. A
later purchase repays that debt before becoming spendable.

## Conservative unit economics

These figures are a planning model, not tax advice. They assume:

- Greek B2C price inclusive of 24% VAT;
- a standard EEA card at 1.5% + €0.25;
- a stress case of 3.15% + €0.25 for an international card plus the possible
  2% currency-conversion uplift;
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

For the three-minute tier, Scribe v2 costs US$0.011. The optional social-copy
ceiling adds US$0.00694; after the 25% provider headroom, the guarded provider
allowance is €0.02242 at conservative USD/EUR parity. Adding the provisional
€0.10 compute, storage and egress allowance gives an all-in planning cost of
€0.12242 per video.

| Three-minute credits | Discount vs 30 | Contribution, standard EEA card | Contribution, international + FX stress |
| ---: | ---: | ---: | ---: |
| 23 | 23.3% | +€0.002 | -€0.006 |
| 24 | 20.0% | +€0.008 | -€0.001 |
| **25** | **16.7%** | **+€0.013** | **+€0.004** |
| 30 | baseline | +€0.040 | +€0.029 |

Twenty-three credits are only a mathematical floor for a standard EEA card;
24 can still lose money in the payment-fee stress case. Twenty-five is the
lowest whole-credit price that remains positive in both modeled cases. Under
the standard EEA case it leaves about 9.6% contribution after the provisional
infrastructure allowance. This is a planning buffer, not a guaranteed net
profit: refunds, failed provider calls, support, fixed hosting and disputes can
still reduce or eliminate it.

The 50-user campaign has a hard face-value cap of 1,500 sponsored credits. At
the 25-credit three-minute tier, each standalone 30-credit grant funds one
first-tier cloud job and leaves five credits. Without later top-ups, the 50
grants therefore expose about €6.12 of modeled provider-plus-infrastructure
cost. If every sponsored credit is eventually combined with purchased credits
and consumed, the prorated ceiling is 60 first-tier job-equivalents, or about
€7.35. Expanding from 20 to 50 adds about €3.67 of standalone exposure, or
€4.41 on the fully allocated basis.

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
10. Provider estimates reserve 25% headroom and must pass a runtime
    contribution guard: the lowest net package value after 24% VAT, the
    international-card fee and the possible currency-conversion uplift must
    cover the guarded provider estimate at least three times.
    Paid calls use zero SDK retries and bounded output tokens. A failed service
    refunds the user's reserved credits idempotently even after dispatch, while
    the operator provider budget remains consumed when the call may have
    reached the provider. Wallet compensation, usage-ledger settlement, and
    provider-budget settlement commit atomically so a crash or retry cannot
    double-refund or strand a reservation. A database-backed dispatch claim
    permits exactly one worker to call the provider. Valid paid fact-check and
    social-copy responses are schema-validated before settlement and stored
    in dedicated temporary replay storage tied to the job lifecycle, so a
    disconnected client can replay the finalized result without a second
    provider call. Invalid paid semantic output fails closed and refunds
    instead of silently returning a local fallback. A later retry after a
    terminal refund is serialized onto one new paid attempt; concurrent retries
    cannot create duplicate provider calls or debits. Stale claims left by a
    crashed winner are reconciled by the retention worker: the customer is
    refunded, guarded provider exposure remains counted, and orphaned budget
    reservations are released atomically with any exact outstanding legacy
    debit compensation.
11. The visible 25/60/100 video charge includes optional social-copy generation;
    it is not deducted a second time.
12. New wallets start at zero credits at both application and database level.
    Historical balances are preserved; paid external-provider work can spend
    only purchased credits.
13. The $0.05 per-request circuit breaker remains narrowly above the guarded
    cost of a maximum ten-minute Scribe v2 job. The $10 daily and $100 monthly
    global ceilings are emergency launch controls, not the source of unit
    economics: at the official $0.22/hour rate and 1.25 reserve multiplier they
    allow more than 200 maximum-length jobs per day and 2,000 per month. Every
    one of those jobs still requires prepaid credits and passes the independent
    3x contribution guard before provider dispatch.

## Live accounting and consumer contract

The owner-authorized live release uses the accountant-reviewed MizAI Greek B2C
workflow as the GSUBS accounting baseline:

- Starter €1, Creator €3 and Studio €10 are final gross prices inclusive of
  24% VAT. Stripe Automatic Tax remains disabled and Checkout is limited to a
  Greek billing address both before authorization and again at signed-webhook
  fulfillment.
- Stripe-hosted Checkout collects the buyer's individual name, email and billing
  address. Stripe handles card details; GSUBS never stores the full card number
  or CVC.
- The Stripe receipt is payment evidence, not an AADE tax document. Ascentia
  issues the tax document manually through e-Timologio and records its series,
  number and MARK against the internal purchase.
- Refund, dispute and withdrawal outcomes remain explicit manual decisions.
  Stripe and AADE are never written by the customer-facing request itself.
- Media workspaces still expire after 24 hours. The minimum payment, invoice
  and MARK snapshot is retained through the end of the fifth full year after
  the relevant tax year, and longer only when required by law or an active tax
  or payment dispute.

The production contract requires the complete live Stripe bundle, the approved
EL/EN disclosure manifest, the byte-identical frontend/backend public-Terms
identity, account-vault contract delivery, and the implemented append-only
adjustment workflow in one exact release. The public `/terms` route contains
the verified Stripe seller identity, operative localized payment/refund text,
and the real `#withdrawal` form. `/privacy` describes active Stripe and AADE
processing.

The live webhook destination is
`https://gsubs.gr/billing/webhook` and subscribes to these 13 events:
`checkout.session.completed`, `checkout.session.async_payment_succeeded`,
`checkout.session.async_payment_failed`, `checkout.session.expired`,
`charge.refunded`, `refund.created`, `refund.updated`, `refund.failed`,
`charge.dispute.created`, `charge.dispute.updated`,
`charge.dispute.funds_withdrawn`, `charge.dispute.funds_reinstated`, and
`charge.dispute.closed`.

Activation never authorizes an unattended charge, refund, AADE document or
billing-admin allowlist change. A real Starter smoke transaction still needs a
separate explicit instruction and full database/Stripe reconciliation.

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

## Live operational guardrails

- The tracked Compose file, backend approval manifest, frontend publication
  identity and verifier must all agree that Checkout is enabled. An environment
  file alone cannot activate or approve sales.
- The live restricted key must retain only Checkout Sessions Write,
  PaymentIntents Write and Refunds Read. The signed webhook must stay active for
  the exact 13-event set above.
- The billing-admin allowlist remains empty until an immutable internal
  `users.id` is separately reviewed. Customer-facing actions never issue AADE
  documents or execute refunds.
- Withdrawal timeliness remains `pending_manual_review`; the application does
  not infer a legal deadline, holiday extension or eligibility result.
- A real €1 smoke transaction requires separate explicit authorization and must
  reconcile Stripe total, `credit_purchases`, `stripe_webhook_events`, wallet
  transactions and the manual AADE record. MARK remains empty until a tax
  document is actually issued.
- Any failure in the production verifier, Stripe bundle, signed-event
  validation, Greece-only address check, provider budget or contract identity
  fails closed without granting credits.

Required environment shape (secrets must not be committed):

```dotenv
GSP_PAID_CREDITS_ENABLED=1
GSP_CONSUMER_POLICY_APPROVED=1
GSP_DURABLE_CONFIRMATION_CHANNEL_READY=1
GSP_ADJUSTMENT_WORKFLOW_READY=1
GSP_STRIPE_API_BASE=http://app-edge:8081/stripe
GSP_STRIPE_RESTRICTED_KEY=
GSP_STRIPE_WEBHOOK_SECRET=
GSP_STRIPE_PRICE_STARTER=
GSP_STRIPE_PRICE_CORE=
GSP_STRIPE_PRICE_PRO=
GSP_STRIPE_SUCCESS_URL=https://gsubs.gr/?checkout=success&session_id={CHECKOUT_SESSION_ID}
GSP_STRIPE_CANCEL_URL=https://gsubs.gr/?checkout=cancelled
GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0
GSP_BILLING_ADMIN_USER_IDS=

GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0.05
GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=10
GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=100
GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER=1.25
```

With `GSP_PAID_CREDITS_ENABLED=1`, startup rejects a missing/ordinary Stripe
key, missing webhook secret, missing Price ID, unsafe production return URL or
Automatic Tax enabled against the approved manual tax workflow. Provider
budgets remain the reviewed production circuit breakers and are consumed only
by requests backed by purchased credits.

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
