# GSUBS privacy and GDPR control pack

Last engineering review: 2026-08-28

This directory is the operational privacy baseline for GSUBS. It translates
the live product behaviour into records and runbooks that Ascentia can actually
use. It is not a legal opinion or a claim that a regulator, lawyer, accountant,
or provider has approved the service.

## Verified controller identity

- Legal name: Ascentia O.E. / Ascentia G.P.
- Greek tax number: `802523620`; EU VAT ID: `EL802523620`
- GEMI registration number: `177974203000`
- EUID: `ELGEMI.177974203000`
- Registered office: Agias Varvaras 4, 16452 Argiroupoli, Athens, Greece
- Privacy contact: `info@ascentia-gp.com`

The VAT number is supported by current AADE tax documents. The legal name,
active status, legal form, office, VAT number, GEMI number, and EUID were
read back from the official GEMI publicity service on 2026-08-28. Store any
downloaded registry extract outside Git; this repository records only the
public identifiers needed by customers.

## Current control status

| Control | Engineering status | Owner action still required |
| --- | --- | --- |
| Public Privacy Policy and Terms | Implemented in Greek and English | Review after every material product/provider change |
| Necessary browser storage | No analytics or advertising storage found; misleading consent banner removed | Re-run a storage/tracker inventory before adding any optional tool |
| Consumer purchase evidence | Versioned, content-addressed, and includes VAT/GEMI/EUID | Keep lawyer/accountant review evidence with the release record |
| Data-subject rights | Product export/deletion plus documented one-month workflow | Monitor the privacy inbox and keep a private request log |
| Processing record | Drafted in `ropa.md` from current code/runtime facts | Controller must review at least annually and on every material change |
| Processor and transfer register | Providers and open evidence tasks recorded | Export and retain the account-level DPA/SCC/subprocessor evidence listed there |
| Personal-data breach response | 72-hour runbook prepared | Assign named incident and privacy decision-makers outside public Git |
| Legitimate interests | Assessment recorded for security, abuse prevention, support, and feedback | Reassess if purpose, data, audience, or retention changes |
| DPO/DPIA/minors screening | Current-facts screening recorded; no blanket exemption claimed | Obtain owner/counsel sign-off and repeat on the documented triggers |
| Real purchase/accounting chain | Application controls exist | A real charge, Stripe refund, or AADE document requires separate action-time approval and reconciliation |

## Mandatory change gate

Before releasing a change that adds a provider, tracker, cookie, new data use,
longer retention, automated decision, model-training use, child-directed
feature, or new country of processing:

1. update the public Privacy Policy and Terms where relevant;
2. update `ropa.md` and `processors-and-transfers.md`;
3. collect the applicable DPA, subprocessors, transfer mechanism, and account
   setting evidence;
4. repeat the DPIA/DPO/minors screening;
5. add targeted regression tests; and
6. do not enable an optional browser storage technology before valid consent.

## Official reference set

- [GDPR consolidated text](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [EDPB guidance on individual rights](https://www.edpb.europa.eu/sme/be-compliant/respect-individuals-rights_en)
- [EDPB guidance on controllers and processors](https://www.edpb.europa.eu/sme/learn-the-basics/data-controller-or-data-processor_en)
- [EDPB guidance on personal-data breaches](https://www.edpb.europa.eu/sme/assess-the-risks/data-breaches_en)
- [Hellenic DPA cookie guidance](https://www.dpa.gr/enimerwtiko/thematikes_enotites/electronikesepikoinwnies/cookies/cookies_diadiktuo_cookies)
- [Official GEMI publicity service](https://publicity.businessportal.gr/)
