# Record of processing activities

Controller: Ascentia O.E. / Ascentia G.P.  
Product: GSUBS  
Review date: 2026-08-28  
Privacy contact: `info@ascentia-gp.com`

This is the engineering-maintained Article 30 working record. The controller
must confirm named internal owners and keep the signed/current copy in its
restricted compliance store.

| Processing activity | People and data | Purpose and lawful basis | Recipients / location | Retention | Main safeguards |
| --- | --- | --- | --- | --- | --- |
| Account registration and authentication | Users; name, email, password hash or Google subject, profile-image URL, verification state, session/security data | Create and secure the account; contract, and legitimate interests in authentication and abuse prevention | Hetzner, Germany; Google Identity when selected | Account lifetime; erased on account deletion except detached records subject to a legal hold | Password hashing, HttpOnly Google nonce, authenticated routes, rate limits, least-privilege deployment |
| Video/audio processing and exports | Users and people appearing in uploaded media; source video/audio, captions, settings, exports, job status | Perform the requested transcription, editing, and export; contract | Hetzner, Germany; extracted audio to ElevenLabs, with possible US processing under the applicable transfer mechanism | Live workspace 24 hours after last edit/export; immediate live deletion on user deletion; encrypted recovery backups up to 14 days; erasure journal 30 days; provider deletion requested immediately with provider backup limits governed separately | Authenticated ownership checks, local isolated volumes, allow-listed provider relay, immediate provider deletion request, replayable erasure journal, encrypted backups |
| Credit balance and usage ledger | Account identifiers, balances, reservations, duration, processing tier, provider-cost evidence | Deliver prepaid service, prevent double spend, investigate disputes; contract and legitimate interests in service integrity | Hetzner, Germany | Active account and then only as needed for contract/dispute evidence; financial records follow the separate row below | Append-only/idempotent ledger events, server-side pricing, fail-closed reservations and refunds |
| Checkout, consumer contract, withdrawal, refund, and tax reconciliation | Buyer identity/contact, billing address, package/price/VAT, Stripe and purchase identifiers, acceptance timestamps/text digests, withdrawal and refund records, AADE series/number/MARK | Conclude and prove the contract, process payment/withdrawal/refund, meet tax/accounting duties; contract, legal obligation, and legal claims | Stripe; Hetzner; AADE e-Timologio in Greece; accountant only under an authorised workflow | Through the end of the fifth full year after the relevant tax year, and longer only for an active legal, tax, or payment dispute | Stripe-hosted card capture, no full card/CVC storage, signed webhooks, immutable snapshots, manual AADE/refund approval and reconciliation |
| Product feedback and support | Optional account identity, message/category, safe page path, pseudonymous abuse key, delivery status | Respond to feedback, improve and protect the service; legitimate interests and steps requested by the user | Hetzner; Google Workspace email | Live inbox up to 180 days or earlier with linked-account deletion; delivered email only while needed to resolve the matter | No raw network address in the feedback record, bounded path, rate limiting, restricted inbox, retry-safe delivery |
| Rights requests and erasure proof | Requester identity evidence, request scope, actions, exceptions, timestamps, pseudonymous erasure entries | Meet GDPR rights and prove compliance; legal obligation and legal claims | Authorised Ascentia staff; processors only where needed to complete the request | Request log kept only for the applicable limitation/compliance period; erasure journal 30 days | Data minimisation, identity verification, one-month deadline, immutable action evidence, legal-hold review |

## Data sources and recipients

Most data comes directly from the user. Google supplies identity data only when
Google sign-in is chosen. Stripe supplies verified payment and billing evidence
after Checkout. System-generated records include job state, usage, deletion,
security, contract, and reconciliation evidence. GSUBS does not sell personal
data, build advertising profiles, or use uploaded media to train Ascentia-owned
AI models.

## Review triggers

Review this record before introducing a new provider or country, a new purpose,
optional tracking, material scale, special-category processing by design,
biometric identification, automated decisions with significant effects, a
longer retention period, or child-directed functionality.

