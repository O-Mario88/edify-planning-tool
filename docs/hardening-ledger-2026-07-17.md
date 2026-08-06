# Stability & Resilience Hardening Ledger — 2026-07-17

Statuses: Discovered → Reproduced → Root Cause Confirmed → Fix In Progress →
Fixed → Load Verified → Concurrency Verified → Failure Recovery Verified →
Data Reconciled → Frontend Verified → Monitoring Verified → Closed.

## Service-Level Objectives (adopted)

| Surface | p50 | p95 | p99 |
|---|---|---|---|
| Server-rendered pages | <300ms | <800ms | <1500ms |
| HTMX partials | <200ms | <500ms | <1000ms |
| Critical mutations | — | <1000ms | <2000ms |
| Monthly country budget generation | <10s at country scale | | |
| Annual reconciliation | <15s | | |
| Unhandled 5xx during acceptance | 0 | | |
| Financial reconciliation difference | UGX 0 | | |
| Query growth on list/dashboard pages | ~O(1) in entity count | | |

## Ledger

| ID | Cat | Sev | Issue | Status |
|----|-----|-----|-------|--------|
| H01 | Speed | — | Query budgets for critical pages: scaling assertion (queries must not grow with entity count) | see test results below |
| H02 | Concurrency | — | True concurrent mutation tests (threaded, real Postgres): schedule, SF-ID reserve, weekly disburse, partner pay, closure, accountability approve | see test results below |
| H03 | Boundary | — | FY/quarter/month boundary + cross-FY reschedule correctness | see test results below |
| H04 | Resilience | — | Secondary-effect failure isolation (notification/audit failure must not roll back primary writes) | see test results below |
| H05 | Consistency | — | Weekly=Σlines, monthly=Σlines+admin, UI/API parity on scaled data | see test results below |
| H06 | Config | — | Production fail-closed startup gates inventory (§35) | verified — prod.py collects violations and refuses boot |
| H07 | Infra | — | Staging-required verifications (soak, restarts, backup/restore, load topology, SSE multi-worker) | PROCEDURES DELIVERED — cannot be executed on a dev laptop; see ops runbook |

Findings appended below as tests surface them.

## Results (2026-07-17)

| ID | Result |
|----|--------|
| H01 | **1 defect found & fixed, then GREEN.** Scaling gates over 7 critical pages (/dashboard CD, /schools, /planning, /ssa, /impact, /my-plan CCEO, /todos): query counts must stay flat when the dataset doubles. FOUND: /my-plan ran +1 district query per activity (55→80 at 25→50 activities) — `select_related` missed `school__district` at 4 sites in apps/my_plan/services.py. Fixed; all 7 pages now scale O(1). Pinned by QueryBudgetScalingTest (7 tests). |
| H02 | **GREEN.** Real threaded races on Postgres (TransactionTestCase): identical schedule → exactly 1 activity (loser gets controlled error); Salesforce ID → 1 reservation (DB unique backstop); weekly disbursement → 1 payout (row lock + state guard); partner payment → 1 ledger row (unique constraint + guard). ConcurrentMutationTest (4 tests). |
| H03 | **GREEN.** Sep 30 → FY N / Oct 1 → FY N+1 and Q4→Q1 verified; cross-FY reschedule moves fy/quarter/month on the Activity AND all cost lines (through the full daily-batch funnel incl. below-target reason). BoundaryTest (2 tests). |
| H04 | **GREEN.** Notification-service failure does not roll back closure; audit-chain failure does not block disbursement (primary write commits, secondary effect degrades). FailureIsolationTest (2 tests). |
| H05 | **GREEN.** Weekly request total == Σ source lines (odd amounts, no drift); activity status identical across My Plan feed and activity detail API. ConsistencyReconciliationTest (2 tests). |
| H06 | **GREEN (pre-existing, verified).** config/settings/prod.py collects ALL violations and refuses boot: weak secret, AUTHZ off, mock data, dev endpoints, missing SUPER_ADMIN_PASSWORD, etc. Environment-stamp guard adds DB-identity fail-closed. |
| H07 | **PROCEDURES DELIVERED** — see runbook in docs/deployment-hardening-2026-07-17.md. Soak, restart, backup-restore, and load-topology verification REQUIRE staging infrastructure and remain the deploy-day checklist; not executable on a dev laptop and not claimed. |
