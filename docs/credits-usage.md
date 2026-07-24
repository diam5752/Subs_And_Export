# Prepaid video credits and Stripe handoff

Updated: 2026-07-23

Paid credits are implemented but fail closed until the owner completes the
Stripe test-mode setup and explicitly enables them. No subscription or
automatic renewal is used.

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

Purchased and promotional credits are separate. Any request that can spend
money at an external provider requires purchased credits; promotional credits
can fund only local/mock work. A refund or dispute claws back unused paid
credits and records debt for credits already consumed. A later purchase repays
that debt before becoming spendable.

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
4. Credits are granted only by a signed webhook whose session ID, PaymentIntent,
   amount, currency, user, package, credits and catalog metadata match the
   stored snapshot.
5. Stripe event IDs are receipt-hashed and serialized with a PostgreSQL
   advisory lock. Duplicate or conflicting payloads cannot grant twice.
6. Every fulfillment, expiry, refund and dispute event affecting the same
   purchase is serialized under a second purchase lock. A PaymentIntent is
   database-unique, and refund/dispute wallet mutations remain event-idempotent,
   including reinstate-then-lost transitions.
7. A provider call reserves paid credits plus daily/monthly USD budget before
   dispatch. Zero budgets mean closed.
8. Provider estimates reserve 25% headroom. Paid calls use zero SDK retries and
   bounded output tokens. Once a call is marked dispatched, a network failure
   cannot trigger another paid attempt or a credit refund.
9. The visible 30/60/100 video charge includes optional social-copy generation;
   it is not deducted a second time.

## Stripe dashboard setup to do with the owner

Do this in **test mode first**:

1. Create three one-time Products/Prices in EUR—Starter €1, Creator €3 and
   Studio €10. Copy their `price_...` IDs.
2. Create a restricted test key. Grant only the minimum Checkout Session
   permissions needed to create and expire sessions; do not use the account
   secret key.
3. Add a webhook endpoint:
   `https://<host>/billing/webhook`.
4. Subscribe to:
   `checkout.session.completed`,
   `checkout.session.async_payment_succeeded`,
   `checkout.session.expired`, `charge.refunded`,
   `charge.dispute.created`, `charge.dispute.funds_withdrawn`,
   `charge.dispute.funds_reinstated`, and `charge.dispute.closed`.
5. Copy the endpoint signing secret (`whsec_...`) to the server secret store.
6. Review the legal seller name, statement descriptor, support contact,
   refund policy and customer email behavior.
7. Decide VAT treatment with the accountant. Automatic Tax deliberately fails
   startup while owner-gated; do not enable it until registrations and
   tax-inclusive prices are confirmed.
8. Set test environment values, run migrations, enable paid credits, and use
   Stripe test cards to cover success, cancellation, delayed payment, duplicate
   webhook, partial/full refund and dispute flows.
9. Reconcile the Stripe payment total, `credit_purchases`,
   `stripe_webhook_events`, point transactions and provider budget windows.
10. Repeat with separate live Prices, restricted key and webhook secret only
    after the test-mode reconciliation passes.

Required environment shape (secrets must not be committed):

```dotenv
GSP_PAID_CREDITS_ENABLED=0
GSP_STRIPE_RESTRICTED_KEY=
GSP_STRIPE_WEBHOOK_SECRET=
GSP_STRIPE_PRICE_STARTER=
GSP_STRIPE_PRICE_CORE=
GSP_STRIPE_PRICE_PRO=
GSP_STRIPE_SUCCESS_URL=https://example.com/?checkout=success&session_id={CHECKOUT_SESSION_ID}
GSP_STRIPE_CANCEL_URL=https://example.com/?checkout=cancelled
GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0

GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0
GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=0
GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0
GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER=1.25
```

With `GSP_PAID_CREDITS_ENABLED=1`, startup rejects a missing/ordinary Stripe
key, missing webhook secret, missing Price ID, unsafe production return URL or
owner-unapproved Automatic Tax. Provider budgets should remain zero until real
provider activation is approved separately.

## Operational verification

```bash
# From repository root
python3 -m pytest --no-cov backend/tests/services/test_billing.py \
  backend/tests/services/test_points.py \
  backend/tests/services/test_provider_budget.py \
  backend/tests/services/test_usage_ledger.py \
  backend/tests/services/test_charge_plans.py \
  backend/tests/test_billing_endpoints.py -q

cd frontend
npm test -- --runInBand
npm run lint
npm run build
npx playwright test --project=chromium
```

Migrations `0008_video_credits_and_billing` and
`0009_reversal_debt_audit`, followed by `0010_unique_payment_intent`, must be
applied before enabling checkout.
