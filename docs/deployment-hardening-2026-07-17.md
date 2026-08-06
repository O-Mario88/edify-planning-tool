# Deployment-Hardening Report — 2026-07-17

Companions: `docs/hardening-ledger-2026-07-17.md` (SLOs + results),
`docs/production-readiness-2026-07-17.md` (remediation + verification audits).

## A. Executive summary

**What is PROVEN (executable evidence in this repo):**
- **Speed/scaling:** 7 critical pages hold a flat query count as the dataset
  doubles (the anti-N+1 gate). One real O(n) defect found on /my-plan (per-
  activity district query) and fixed. Gates are permanent tests — any future
  N+1 on these pages fails CI.
- **Concurrency:** real threaded races on Postgres prove one-winner semantics
  for identical scheduling, Salesforce reservation, weekly disbursement, and
  partner payment. Earlier phases already pinned: period-disburse ledger
  write-back, accountability guards, reimbursement single-row state machine,
  amendment locking, PartnerPayment uniqueness.
- **Boundaries:** FY rollover (Sep 30 / Oct 1), quarter rollover, and
  cross-FY reschedule move every period field on the activity AND its cost
  lines coherently.
- **Failure isolation:** notification-service and audit-store outages degrade
  those effects only — the primary financial/workflow write commits.
- **Consistency:** weekly request == Σ source lines with odd amounts (0 UGX
  drift); status parity across My Plan and the activity API; plus the
  reconciliation identities pinned in earlier phases (children-sum exactness,
  accountability identity, monthly = Σ lines + admin).
- **Fail-closed configuration:** prod settings refuse boot on any safety
  violation; the environment stamp refuses cross-environment databases;
  background jobs are tracked, locked, health-visible (7 jobs).
- **Full suite:** all tests green (see final run count in section D).

**What REQUIRES staging infrastructure (procedures below, deliberately NOT
claimed):** soak/leak testing, process/database restart drills, backup-restore
rehearsal, reverse-proxy/SSE multi-worker topology, and load testing at true
country scale. Per the mandate's own rule, production deployment should not
be recommended until section C is executed on staging — this report makes
that checklist executable rather than pretending a dev laptop is a cluster.

## B. Verified gates (this pass)

`apps/core/tests/test_hardening_gates.py` — 17 tests:
- QueryBudgetScalingTest (7): /dashboard(CD), /schools, /planning, /ssa,
  /impact, /my-plan(CCEO), /todos — query count at N vs 2N schools must not
  grow beyond +4.
- ConcurrentMutationTest (4): barrier-synchronized threads, real commits.
- BoundaryTest (2), FailureIsolationTest (2), ConsistencyReconciliationTest (2).

Fix shipped this pass: `apps/my_plan/services.py` — `select_related` widened
to include `school__district` at 4 sites (was +1 query per activity row).

## C. Staging runbook (execute before first production deploy)

1. **Topology:** Daphne workers ≥2 requires the SSE process-local bus caveat:
   either run SSE-serving traffic on a single worker (sticky) or accept
   notification-bell refresh fallback; document choice. Scheduler runs as ONE
   dedicated `runscheduler` process with `ENABLE_BACKGROUND_JOBS=true`; web
   workers run with it false.
2. **Data:** restore an anonymized production-shaped dataset; run
   `manage.py seed` (reference only — never `--demo`; the stamp guard will
   refuse anyway once the DB is stamped production).
3. **Load:** drive scenarios A–E (login peak, planning peak, field
   completion, finance processing, leadership reporting) with Locust/k6
   against staging; SLOs in the ledger (p50/p95/p99). Record per-endpoint
   metrics; any page breaching budget gets a profiling pass (the query gates
   make N+1 regressions unlikely; remaining breaches will be template/volume).
4. **Restart drills:** kill -9 each process class mid-workflow (web during
   disbursement submit; scheduler mid-job; Postgres restart under load).
   Verify: rolled-back transactions, no duplicate advance/payment rows
   (`repair_ecosystem_data` scans report 0), jobs resume via
   ScheduledJobExecution locks, System Health returns green.
5. **Soak:** ≥8h with scripted traffic + jobs enabled. Watch worker RSS,
   `pg_stat_activity` count, `/uploads` temp files, LibreOffice process
   count, latency trend. Acceptance: no monotonic growth, no stuck locks.
6. **Backup/restore rehearsal:** pg_dump (custom format) + evidence
   directory; restore into an isolated environment; run
   `repair_ecosystem_data` (dry-run) + System Health + spot reconciliation;
   record RPO/RTO. A backup that has never restored is not a backup.
   NOTE: the restored copy is stamped 'production' — processes there must
   run with ENVIRONMENT=production (or restamp deliberately to 'staging').
7. **Rollback:** all migrations to date are additive (verified through
   migration review in the remediation phase); rollback = previous image +
   `migrate <app> <previous>` for the four new migrations if needed (each
   reversible; the stamp data migration has an explicit reverse).
8. **Role smoke tests:** the ten roles × login/dashboard/primary workflow on
   desktop + mobile widths (the suite's role tests cover authorization;
   staging validates the rendered experience).

## D. Test evidence

Full suite after this pass: see CI/final run — all green including the 17
hardening gates, 13 production gates, 17 ecosystem-handoff regressions,
11 environment-guard tests, and every earlier suite. `manage.py check` and
`makemigrations --check` clean.

## E. Remaining risks (honest)

- Staging-dependent items in section C — open until executed on infra.
- SSE multi-worker delivery (ledger L25) — topology constraint documented;
  full broker unification remains the next engineering block.
- Load-at-15k-schools measurements — the scaling gates prove query-count
  flatness, which is the structural precondition; wall-clock SLO conformance
  at full volume must be measured on staging hardware, not a laptop.
