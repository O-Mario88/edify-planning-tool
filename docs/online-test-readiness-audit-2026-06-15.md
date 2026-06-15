# Edify — Online First Test Readiness Audit (2026-06-15)

Strict computation-logic / data-quality / workflow-accuracy / role-scope / decision-readiness audit.
Method: trace every decision-critical number FE → backend service → raw Postgres records; reconcile;
classify P0–P3 with evidence. Read-only discovery first, then fixes.

## Environment baseline (verified)

| Check | Result |
|---|---|
| Web unit tests (`vitest run`) | ✅ 590 passed (48 files) |
| Backend unit tests (`vitest run`) | ✅ 112 passed (12 files) |
| Web typecheck (`tsc --noEmit`) | ✅ clean |
| Web production build (`next build`) | ✅ exit 0, all routes compiled |
| Postgres `edify_pm` | ✅ up; 700 School, 38 User, 268 Activity |
| Backend API `:4000/api/health` | ✅ `{status:ok, db:up}` |
| `npm run mock:audit` | ⚠️ 381 files import mock; **62 page routes** still import mock |
| `npm run prod:check` | ❌ **GATE FAILED** — mock-leakage gate + EDIFY_USE_BACKEND |

Seeded data state (so empties/leaks are visible):
`FundRequest=1 (disbursed)`, `PaymentRequest=8 (4 netsuite_accountability, 4 ia_confirmed)`,
`Leave=0`, `EvidenceRecord=26 (7 uploaded, 19 accepted)`, `LeadershipDecisionInsight=0`,
`SsaRecord: FY2025=490, FY2026=210`. Activity.status: completed 234, ia_verified 9,
awaiting_ia_verification 9, scheduled 4, partner_scheduled 3, assigned_to_partner 3,
evidence_uploaded 3, planned 2, in_progress 1.

---

## Orchestrator-confirmed findings (independent of the agent fan-out)

### P0-A — `seedDemoStore()` injects FAKE data into production
- File: `src/lib/actions/store.ts:391-393`. Guard is only `if (process.env.NODE_ENV === "test") return;`
  — it does **not** guard production. On any non-test boot the in-memory store is seeded with a
  fabricated plan `PLAN-DEMO-PC-2606`, 8 demo activities, fake Salesforce IDs (`SVE-40231`…),
  and a fake NetSuite expense id `6161`.
- Blast radius: **27 importers** of `@/lib/actions/store`, incl. page routes
  `/dashboards/accountant`, `/dashboards/director`, `/my-plan`, `/partner/evidence`, `/plans`,
  `/schools/[id]`, the **`api/cceo/my-plan` route**, and libs `my-plan-sections.ts`,
  `cceo/evidence-queues.ts`, `funds/live-approval-queue.ts`, `quality/quality-checks.ts`.
- Impact: production users (incl. the Accountant finance funnel) see fabricated numbers. **Fake
  production data visible → P0.**
- Fix: guard the seed behind the mock policy — `if (!isMockAllowed()) return;` (covers prod + test).

### P0-B — `/decisions` renders hand-mocked leadership recommendations
- File: `src/app/(shell)/decisions/page.tsx` — header comment admits "the board is hand-mocked …
  the engine wiring lands in a later turn." Calls `decisionBoardFor(role)` from `decisions-mock`
  and `decisionActionsForCreator/Assignee` from `field-intelligence-mock`. **No backend fetch, no
  `isMockAllowed()` guard.** `LeadershipDecisionInsight` table = 0 rows.
- Impact: leadership would act on fabricated recommendations. **P0.**
- Fix: fetch from the live leadership engine (`/api/leadership/*`) and show "Insufficient data" empty
  state when the engine returns nothing; remove the mock board in prod.

### P1-C — Frozen FE clock vs real backend "now" vs seed dates (period mis-bucketing)
- `src/lib/clock.ts` pins `ENGINE_NOW_ISO = "2025-11-15"` (FY2026 **Q1**, 25% cumulative target) for
  every FE FY/quarter/pace/cycle computation. Backend `edify-api/src/common/fy/fy.util.ts` defaults
  to real `new Date()` → today (2026-06-15) = FY2026 **Q3** (75% target).
- For an online test on a real date, FE "Due Today / This Week / This Month" and cumulative-target %
  reference Nov 2025, not the test date — buckets mis-fill.
- Fix: production must use real now (the file documents the one-line swap), and the seed must be
  re-dated to the test window so buckets fill correctly — OR keep the freeze and date the seed to it
  consistently. Decide one clock.

### P1-D — Activity period columns disagree with `scheduledDate` (data integrity)
- `Activity.scheduledDate` = 2026-05-11 … 2026-06-24 (FY2026 **Q3** by the FY rules), but
  `Activity.quarter` = **Q2** for 266/268 rows and `Activity.plannedMonth` = 4 for 234 rows.
- Any surface grouping by `quarter` shows Q2; any filtering by `scheduledDate` shows Q3 — same
  records, different period totals. Silent calculation error.
- Fix: re-derive `quarter`/`plannedMonth`/`plannedWeek` from `scheduledDate` in the seed (and add a
  backend invariant/test that they agree).

---

## Agent fan-out findings (appended after verification)

_(populated from the truth-audit workflow)_
