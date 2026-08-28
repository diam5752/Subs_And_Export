# Processor, recipient, and transfer register

Review date: 2026-08-28

Public provider terms are useful evidence but are not a substitute for retaining
the terms and settings that apply to Ascentia's actual account. `OPEN` below
means the control must be completed in the private compliance store; it does
not mean a DPA or setting is active merely because a provider advertises it.

| Provider / recipient | Role and data | Primary processing location / transfer | Public contract reference | Account-level evidence status |
| --- | --- | --- | --- | --- |
| Hetzner Online GmbH | Processor for application, PostgreSQL, local media volumes, encrypted backups, and infrastructure logs | Germany / EEA; no non-EEA transfer intended for this lane | Provider data-processing terms in the customer account | **OPEN:** export the current DPA, region/order details, and authorised-user list |
| ElevenLabs | Processor for extracted audio and generated transcript; deletion identifier retained locally | Standard service may process/store in the US; use the operative DPA transfer mechanism, including SCCs where applicable | [DPA](https://elevenlabs.io/dpa), [subprocessors](https://compliance.elevenlabs.io/), [data residency](https://elevenlabs.io/docs/overview/administration/data-residency) | **OPEN:** retain the incorporated DPA/version, subprocessor list, transfer mechanism, account region, and whether Zero Retention or EU residency is actually enabled. Until proved, assume neither optional mode is active |
| Stripe Payments Europe | Independent controller and/or processor according to the payment activity; buyer identity, billing address, payment and dispute data | EEA and documented global support/processing locations under Stripe's terms | [Stripe privacy and data-processing terms](https://stripe.com/privacy) | **OPEN:** export the account DPA/terms, authorised users, webhook configuration, and current subprocessor/transfer evidence |
| Google Identity | Authentication provider; name, email, subject, verification state, optional profile-image URL | Google infrastructure, potentially outside the EEA under the applicable terms | [Google privacy terms](https://policies.google.com/privacy) | **OPEN:** retain OAuth configuration, scopes, account terms, and transfer evidence; approved scopes must remain identity-only |
| Google Workspace | Processor for the `ascentia-gp.com` mailbox and delivered feedback/support email | Configured Workspace region and Google's documented transfer mechanisms | [Google Workspace data-processing terms](https://workspace.google.com/terms/dpa_terms.html) | **OPEN:** export the current DPA, data-region setting, admin/MFA list, retention setting, and subprocessor evidence |
| AADE e-Timologio | Public authority/recipient for tax documents actually issued; not classified here as an Ascentia processor | Greece | Applicable Greek tax law and AADE service terms | Keep issued-document and MARK reconciliation evidence in the restricted accounting file |

## Transfer impact record for ElevenLabs

Current product facts reduce but do not eliminate transfer risk:

- only extracted audio is sent through method/path-restricted infrastructure;
- provider output is copied locally and deletion is requested immediately;
- a 30-day local deletion journal supports retries;
- Zero Retention Mode and EU residency are not claimed without account proof;
- source media and exports remain on the Hetzner application volume; and
- uploaded content can still contain voices, names, opinions, health details, or
  other sensitive material chosen by the customer.

Before representing this transfer as approved, the private assessment must
record the applicable DPA/SCC version, destination(s), subprocessors,
supplementary technical measures, government-access assessment, account
settings, decision-maker, decision date, and next review date. If that evidence
cannot be obtained or the residual risk is unacceptable, disable the provider
route; do not silently fall back to another external processor.
