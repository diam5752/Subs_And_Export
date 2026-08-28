# DPIA, DPO, and minors screening

Engineering screening date: 2026-08-28  
Decision status: provisional; controller/counsel sign-off not stored in Git

## Current facts

- GSUBS transcribes and edits user-selected media; uploaded material may
  incidentally contain other people's personal or sensitive data.
- The service is not designed for systematic public monitoring, biometric
  identification, credit/employment/health decisions, behavioural advertising,
  or solely automated decisions with significant effects.
- The service is not specifically directed at children. Users lacking legal
  capacity must involve a parent/guardian, and purchases require legal capacity
  or valid authority.
- Uploaded media is short-lived locally, provider deletion is requested, and
  the product does not train Ascentia-owned models on it.
- Standard ElevenLabs processing may involve the United States and needs the
  separate transfer evidence recorded in `processors-and-transfers.md`.

## Provisional outcome

On the current documented scale and purposes, engineering has not identified a
clear mandatory-DPO trigger or a planned high-risk processing operation that
can be treated as approved only after a DPIA. This is not a legal exemption and
does not resolve the open provider-transfer evidence. The controller should
record a signed decision and obtain specialist advice if factual scale or use
differs from this record.

## Mandatory rescreening triggers

Complete a DPIA/DPO rescreening before release if GSUBS:

- targets children or verifies/infers age at scale;
- processes special-category or criminal-offence data by design or at scale;
- identifies faces/voices biometrically;
- systematically monitors people or public spaces;
- profiles or makes decisions with legal/similarly significant effects;
- combines unrelated datasets, trains models on customer content, or reuses
  media for a new purpose;
- materially increases volume, retention, geographic scope, or provider access;
- introduces a new non-EEA transfer without completed safeguards; or
- suffers an incident showing that the current risk assumptions are wrong.

The rescreening record must name the decision-maker, facts, risk criteria,
consultation, mitigations, residual risk, approval date, and next review date.

