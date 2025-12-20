# Credits, Usage Ledger, and Testing

## What Changed
- Replaced multi-model transcription choices with a 2-tier system: Standard (Groq Turbo) and Pro (Groq Large).
- Added a usage ledger that reserves credits up front and finalizes charges based on actual usage.
- Made credit deductions idempotent to prevent double-charges on retries.
- Added admin usage summaries for daily/monthly/user/action rollups.
- Updated UI copy and pricing displays to reflect tiered minimums.

## Credit Flow (Backend)
1. **Reserve** credits on request start (usage ledger row created with status `reserved`).
2. **Finalize** after provider response (credits adjusted to actual usage + minimums).
3. **Refund** if a job fails before usage is recorded.

Key files:
- `backend/app/services/usage_ledger.py` (reservation/finalize/refund + summaries)
- `backend/app/services/charge_plans.py` (standard/pro charge helpers)
- `backend/app/services/pricing.py` (tier pricing + token/minute math)
- `backend/app/core/config.py` (tier defaults and credit rates)

## Admin Usage Summary
Endpoint (admin-only, gated by `GSP_ADMIN_EMAILS`):
```
GET /videos/admin/usage/summary?group_by=day|month|user|action&start_ts=...&end_ts=...
```
Response includes totals for credits reserved/charged and cost USD per bucket.

## Testing
Backend:
```
pytest
```

Frontend:
```
cd frontend
npm test -- --watchAll=false
```

If you need to re-run migrations locally:
```
alembic upgrade head
```
