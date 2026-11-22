# Edify Staging Cutover & Pre-Production Sign-Off Kit

Automated verification tools for the 4-step sign-off sequence in `docs/audit/PRODUCTION_READINESS.md`.

> **NON-NEGOTIABLE SAFETY:** Never run `uat_journey.py` or `soak_test.py` against production. Only run `hygiene_check.sql` (100% read-only) on a sanitized staging snapshot clone.

## 1. Read-Only Data Hygiene Check (`DATA-001` & `DATA-002`)
```bash
psql "$STAGING_READONLY_DATABASE_URL" -v ON_ERROR_STOP=1 -f hygiene_check.sql
```
Verifies:
- `school.sub_region_id` vs `district.sub_region_id` coverage
- `ssa_record.average_score` vs `AVG(ssa_score.score)` reconciliation
- Activity Sunday-date and fiscal-year alignment
- `school_id` uniqueness and non-negative financial balances

## 2. Multi-Role Staging UAT Ecosystem Runner (Django Offline)
Start the Go gateway with `EDIFY_EXISTING_APP_URL=""`, `EDIFY_STRICT_READS=true`, and `EDIFY_REDIS_URL="rediss://..."`, then run:
```bash
python3 uat_journey.py \
  --gateway "$STAGING_GATEWAY_URL" \
  --db "$STAGING_DATABASE_URL" \
  --jwt-secret "$EDIFY_JWT_SECRET"
```

## 3. Sustained 1,000-User Staging Soak Test
```bash
python3 soak_test.py \
  --gateway "$STAGING_GATEWAY_URL" \
  --token "$STAGING_JWT" \
  --users 1000 \
  --duration 3600
```
Pass criteria: `0` errors (`error_rate_pct == 0`), `P95 <= 1000 ms`, steady memory & DB pool utilization under PgBouncer + Redis Pub/Sub.
