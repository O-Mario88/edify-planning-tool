# Backend and database performance report

## Scale result

The scale suite passed at `EDIFY_SCALE_SCHOOLS=15000` and `EDIFY_SCALE_GROWTH=3000` (21 tests). Its latest recorded p95 values were:

| Route | p95 |
|---|---:|
| `/dashboard` | 493 ms |
| `/my-plan` | 71 ms |
| `/schools` | 189 ms |
| `/todos` | 205 ms |
| `/notifications` | 21 ms |
| `/settings` | 16 ms |
| `/analytics` | 533 ms |
| `/system-health` | 11 ms |

All are below their relevant proposed server thresholds in this local scale harness.

## Confirmed database optimization

`/core-schools/champion-candidates` previously issued more than 9,000 queries and took 23.538 seconds. The service now batches eligibility facts, avoids per-row writes, and bulk-updates only changed statuses. The regression contract measures 5 queries and the optimized service completed in 0.281 seconds on the high-volume local dataset.

The page-selector changes also avoid transferring approximately 16,988 school records to the browser. Search results are permission-scoped and capped at 25.

No new migration drift exists (`makemigrations --check --dry-run` passed). Two migrations carry the governed rate-card kind and monthly funding-envelope snapshot fields.

## Costing correctness

- Operational and regional amounts are computed from the same activity inputs across canonical cost components.
- Monthly phasing applies the same proportional allocation to regional and operational line amounts.
- Regional configuration is mandatory for a regional ceiling; the service does not fabricate it from operational values.
- The CD submission equals the full regional ceiling, split into operational activity requirement and explicit strategic reserve.
- RVP approval persists the envelope/reserve, while staff authority remains the operational amount.
- Snapshot fields and per-line amounts preserve the approval-time financial record.

## Production backup recovery

BACKUP-01 passed a real managed-cluster restore rehearsal. The isolated fork
promoted in 4m28s; two release migrations applied in 201s; all eight critical
authenticated pages, 13 sequences, and the 1,713-row audit chain passed on the
restored copy. See [the production restore evidence](10-production-backup-restore-rehearsal.md).

## Not available

No production-equivalent PostgreSQL instance was available for `EXPLAIN ANALYZE`, `pg_stat_statements`, lock-wait/deadlock review, connection saturation, bloat, or production index-use analysis. Those are unclosed database acceptance gates.
