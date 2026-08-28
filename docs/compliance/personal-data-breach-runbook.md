# Personal-data breach response runbook

This runbook applies to confidentiality, integrity, or availability incidents
involving personal data, including lost deletion evidence or an unsafe restore.
It does not authorise public statements, provider changes, refunds, or tax
actions automatically.

## First response

1. Start an incident record with UTC discovery time, awareness time, reporter,
   systems, data, people, countries, and current evidence. Preserve logs and
   avoid destructive cleanup.
2. Contain safely: revoke exposed credentials, isolate affected paths, stop
   processing, or keep a restore offline. Maintain the erasure journal and
   backup chain; never restore user data when continuity proof is missing.
3. Notify the controller's incident and privacy decision-makers immediately.
   Notify an affected customer/controller without undue delay when Ascentia is
   acting as its processor.
4. Determine whether personal data was destroyed, lost, altered, disclosed, or
   accessed without authorisation. Record categories, approximate people and
   records, sensitivity, identifiability, duration, likely consequences, and
   protections such as encryption.

## Regulatory and individual notification

- Record every personal-data breach, including the facts, effects, decision,
  and remediation, even when no external notification is required.
- If the breach is likely to create a risk to people's rights and freedoms,
  notify the Hellenic Data Protection Authority without undue delay and, where
  feasible, within 72 hours after awareness. If later, explain the delay.
- If it is likely to create a high risk, notify affected people without undue
  delay in clear language unless a documented GDPR exception applies.
- A notification should cover the breach nature, privacy contact, likely
  consequences, and measures taken or proposed. Supply information in phases
  if it cannot all be provided at once.

## Decision record template

- Incident ID and UTC timeline
- Systems/providers and controller/processor role
- Data/people/records and countries affected
- Confidentiality, integrity, and availability impact
- Risk and high-risk assessment with evidence
- DPA notification required: yes/no; decision-maker; time; reference
- Individual notification required: yes/no; exception; time; channel
- Processor/customer/provider notifications and references
- Containment, recovery, validation, and long-term corrective actions
- Closure approval and review date

Use the [EDPB breach guidance](https://www.edpb.europa.eu/sme/assess-the-risks/data-breaches_en)
and the [Hellenic DPA](https://www.dpa.gr/) reporting channel current at the
time of the incident; do not rely on a stale saved form.

