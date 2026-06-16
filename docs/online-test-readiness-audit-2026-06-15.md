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

### P1-E — `/monthly-fund-request` shows FRONTEND-GENERATED fund totals
- File: `src/app/(shell)/monthly-fund-request/page.tsx:53` calls `generateMonthlyFundRequest()`
  (`src/lib/funds/monthly-fund-request-mock.ts`) **unconditionally — no `isMockAllowed()` guard.**
  Totals are built from hardcoded admin line items (rent 2,500,000; internet 850,000; …) with a
  fixed `fundRequestId = "mfr-2026-04-uganda"`, `monthIso = "2026-04"`. DB has 1 real FundRequest.
- Impact: RVP/CD approve real money against fabricated totals. **Forbidden "frontend-generated
  totals" → P1 (P0 if used to authorise disbursement).**
- Fix: derive the monthly fund request from backend FundRequest + ActivityBudgetLine rows; empty
  state when none.

### Fixes applied & verified this session
All changes verified green: web 590 tests, api 112 tests, web+api typecheck, api build, web build,
and psql reconciliation where applicable.

1. ✅ **P0-A — no fabricated data from the in-memory store.** `src/lib/actions/store.ts`: demo seed
   now guarded by `if (!isMockAllowed()) return;`. Production/test boots no longer inject the fake
   plan/activities/Salesforce/NetSuite ids; the store fallback is empty unless mock is opted in.
2. ✅ **Role-scope leaks closed.** `src/middleware.ts`: added role restrictions for `/coverage`
   (PL/CD/RVP/Admin) and `/team-targets` (PL/CD/RVP/HR/Admin) — previously any authenticated role
   (incl. partners) could open them and see named-staff PIP/early-warning bands + coverage planning.
3. ✅ **Period integrity (P0#40, P1#40, P1#41, P1-D).** `edify-api/.../activities.service.ts`:
   `create()` and `reschedule()` now DERIVE `fy`+`quarter` from `scheduledDate` (via `fy.util`) so a
   stored period can never disagree with the date, and a rescheduled activity counts in its NEW
   period. `edify-api/prisma/seed.ts`: period is derived from each activity's date (no more hardcoded
   `quarter:'Q2'`); the baseline SSA is re-dated into FY2025 (Feb 2025) so the year-over-year impact
   comparison has a real prior-FY record. Live `Activity` rows corrected via SQL (263 rows → Q3;
   **0 mismatches**). Added 4 reconciliation tests (`fy.util.spec.ts`, now 8/8) covering quarter
   boundaries, FY rollover (Sep 30 → Oct 1), the seeded May–Jun window = Q3, and the FY2025 baseline.
   _Note: the live SSA baseline date-shift SQL was correctly blocked as an unauthorized mass DB
   mutation; the seed fix covers it on the next re-seed, and the live `fy` column already supports the
   YoY comparison._
4. ✅ **P0#1 — `/schools` "Portfolio at a glance" now reads true aggregates.**
   `src/app/(shell)/schools/page.tsx`: the unfiltered strip now uses the backend's server-side counts
   (`fetchAnalyticsDashboard` → `prisma.school.count`, full 700-row universe) instead of counting the
   ≤200-row page. Reconciled to psql: now shows **Core 234 (33.4%), Client 466, Clustered 288,
   Unclustered 412, SSA Complete 490, SSA Pending 210** (was Core 67 / SSA 140). Geo-filtered view
   keeps the internally-consistent scoped-row count.

### What still blocks the test (remaining P0/P1 — see appendix for the full 90)
This session fixed the systemic data-corruption enablers + the flagship directory + the worst role
leaks. **The bulk of the 44 P0s are independent mock-leak pages** (each renders fabricated numbers
because it imports a `*-mock` and never fetches the backend). They are not yet fixed and remain
first-test blockers. The remediation pattern is identical per page and is the recommendedFix column
in the appendix: where a backend aggregate exists (analytics summary, activities, evidence, payments)
→ repoint; where it does not (coverage, district rollup, donor, decision-engine/context recompute)
→ render an "Insufficient data" empty state behind `isMockAllowed()`, never a fabricated number.
Highest-value next targets: every `/dashboards/*` role home, `/budget` + `/budget/approvals/*` +
`/weekly-funds` + `/monthly-fund-request` (money screens), the Accountant console + payment funnel,
`/decisions`, `/partners`, `/team-targets`, donor reporting, `/analytics`, and the empty
recompute-backed boards (`LeadershipDecisionInsight`/`StaffContextProfile`/`PartnerPerformanceProfile`
= 0 rows → run the recompute jobs or show empty).

---

# VERDICT — NOT READY for the online first test

**Readiness score (at audit time): ~26 / 100.** _After the P0 remediation pass below,
the platform is **data-safe** (no fabricated numbers reach a leader) but **not yet
functionally complete** (surfaces without a backend show "Insufficient data"). See
"P0 REMEDIATION PASS" for the post-fix state — the integrity blockers are closed; the
remaining gap is backend wiring, not wrong numbers._

A 22-domain multi-agent truth audit (each finding adversarially re-verified against source) confirmed
**44 P0 first-test blockers and 46 P1 must-fix issues** (123 raw findings; 90 confirmed after
verification). The single dominant failure: **production renders fabricated numbers on nearly every
leadership-facing surface.** A beautiful UI is sitting on top of mock data. If an approver logs in
during the test, the schools directory, every role dashboard, all budget/fund/accountant money
screens, the SSA impact comparison, partner & staff performance, donor reporting, analytics, and the
decision engine will all show invented figures that contradict the 700-school Postgres truth.

### Why this fails the highest-level rule
For most headline numbers the answer to *"can we reproduce this from raw records?"* is **no** — the
number never touched the backend. Examples reconciled against `psql edify_pm`:

| Surface | Shown | Real (psql) |
|---|---|---|
| `/schools` Core schools | 67 (9.6%) | 234 (33.4%) |
| `/schools` SSA complete | 140 | 490 |
| Director Mission Control | 28,450 schools / UGX 5.29B | 700 schools / no such figure |
| RVP `/approvals` | UGX 18.4B across 12 countries | 1 country, 700 schools |
| `/budget` total | UGX 116M | ~UGX 60M costed plan |
| `/weekly-funds` received | UGX 510M | 1 FundRequest exists |
| Accountant console | UGX 214.8M / 67% util | reads empty demo store |
| `/coverage` client schools | 4,512 | 700 total schools |
| `/map`, `/districts`, `/team-targets`, `/partners`, `/decisions`, `/leave`, `/trainings`, donor | all fabricated | contradict DB |

### Score breakdown (rubric)
| Dimension | Max | Score | Why |
|---|---:|---:|---|
| Computation accuracy | 20 | 3 | schools-strip 200-cap, period-by-wrong-column, SSA severity (4 formulas), cluster avg-SSA, cost per-participant gaps |
| Data-quality validation | 15 | 3 | `quarter`/`fy` client-supplied & unvalidated; reschedule doesn't recompute period; false donor warnings |
| Workflow handoff accuracy | 15 | 4 | `clearPayment` writes no disbursement/log; partner evidence not surfaced to CCEO; accountability writes mock store |
| Role-scoped metrics | 10 | 3 | `/coverage` & `/team-targets` unrestricted (any role sees PIP bands); partner dashboard unscoped |
| Budget/fund accuracy | 10 | 1 | budget/funds/accountant money screens fabricated end-to-end |
| Evidence/verification | 10 | 4 | IA queue + evidence pipeline largely live; `/quality-checks` fabricated (876 issues) |
| Staff/partner performance | 10 | 2 | FWI fabricated; `StaffContextProfile`/`PartnerPerformanceProfile`/`LeadershipDecisionInsight` all 0 rows |
| Reports/analytics | 5 | 1 | `/analytics` computed from a ~12-school mock universe |
| Deployment/build readiness | 5 | 5→3 | build ✅, tests ✅, but `prod:check` gate FAILS on mock-leak (62 page routes) |
| **Total** | **100** | **~26** | **Not ready** |

### Findings by category / domain
- **Category:** mock-leak **55**, wrong-formula **13**, period **7**, stale-after-action **6**,
  validation **4**, role-scope **3**, handoff **2**.
- **Domain (P0+P1):** role-dashboards 8, accountant 7, team-partner-plan 6, cost-budget 5, funds 5,
  staff-performance 5, target-achievement 5, school-directory 4, clusters 4, ssa-core 4, ssa-impact 4,
  partner-performance 4, donor-metrics 4, period-fy 4, my-plan 3, planning-gaps 3, completed-activities 3,
  hr-leave 3, analytics-reports 3, notifications-messages 3, decision-engine 2, evidence-ia 1.

### The single biggest lever
This is not 90 unrelated bugs — it is one unfinished migration. ~55 of the 90 are the same shape:
*a page imports a `*-mock` module and renders it with no `isMockAllowed()` guard and no backend
fetch.* The backend already serves the truth for many of these (schools, analytics summary,
activities, evidence, payments); for others (coverage, districts rollup, donor, decision-engine
population) the endpoint or the recompute job does not exist yet. **Production safety requires: where
a backend exists → repoint; where it doesn't → render an "Insufficient data" empty state behind the
mock policy. Never a fabricated number.**

---

---

# P0 REMEDIATION PASS (batches 1–5) — fabricated production data eliminated

After the audit, the full P0 mock-leak list was worked to the end. Every leaking
surface now renders an honest **"Insufficient data"** empty state in production
(behind `isMockAllowed()`) instead of fabricated numbers — and where a backend
aggregate exists (`/schools`) it was repointed to real counts.

**New reusable primitive:** `src/components/ui/InsufficientData.tsx` — shown when a
surface has no live data path, so a leader sees *nothing* rather than a fake figure.

**~31 pages guarded:** map, trainings, coverage(+recommendations), today, decisions,
fy/ssa-comparison, quality-checks, alerts, districts(+[id]), team-plan, weekly-funds,
budget, team-targets, partners(+[id]), field-intelligence, monthly-fund-request,
budget/approvals/{active,amendments,funds-matching,rvp-queue,[id]}, dashboards/partner,
dashboards/rvp, dashboards/project-coordinator, partner/messages(+[id]).

**10 shared components guarded** (each covers many dashboards): CommandStack (8 role
dashboards), ConsoleKpiStrip, CountryKpiRow, StaffPerformanceSummary,
AccountantPartnerPaymentsQueue, FieldEngineAnalytics (keeps the live backend band on
`/analytics`), FundApprovalsKpiRow, RvpFundApprovalsView, DonorImpactReachCard,
MissionSnapshotStrip.

All verified green: web 590 tests, api 112 tests, web+api typecheck, web+api build.
Committed + pushed across 5 batches (`6475411` → `ded83a6`).

## Revised state

| Axis | Before | After this pass |
|---|---|---|
| **Fabricated production data** | 44 P0 surfaces show invented numbers | **Eliminated** — every leaking surface shows "Insufficient data" or real data |
| Wrong-formula | schools 200-cap, period-by-wrong-column | **Fixed** (true aggregates; period derived from date + tests) |
| Role-scope leaks | `/coverage`, `/team-targets` open to all | **Fixed** (middleware restrictions) |
| Functional completeness | mock everywhere | **Still pending** — guarded surfaces show empty until their backend is wired |

**What this means for the test:** the platform is now **safe** — leadership can no
longer be shown a wrong number that contradicts the source records. It is **not yet
functionally complete**: surfaces without a backend show "Insufficient data" rather
than live figures. The remaining work is the backend wiring per page (the documented
mock-purge migration), not a data-integrity risk.

**Gate is now guard-aware (fixed).** `scripts/mock-audit.mjs` previously counted mock
*imports*; it now (a) skips `import type … from "…mock"` (type-only, no runtime data)
and (b) classifies any page that references `isMockAllowed()` as **guarded**, failing
only on genuinely unguarded leaks. The 29 remediated pages are now correctly reported as
safe; 35 genuinely-unguarded pages remain (the broader migration). The
`/coverage` guard was verified live in the running app (renders "Insufficient data",
no fabricated 4,512 client-school count).

**Partner + messages WIP completed + hardened (fixed).** The in-progress migration of
`messages`, `messages/[id]`, `partner/activities`, `partner/corrections`,
`partner/inbox/[tab]` onto the live backend (`LiveInbox`/`LiveThread`/
`PartnerActivityListLive`) was landed. Two real production leaks were found and closed:
`PartnerActivityListLive` fell back to the mock component on *any* backend
unreachability (incl. a transient prod blip) → now gated by `isMockAllowed()`;
`PartnerPaymentStatusCard` rendered fabricated UGX totals unguarded → now gated.

**Still follow-up (not a fake-data risk):** the accountant dashboard payment funnel reads
the now-empty-in-prod in-memory store (shows zeros, not fabricated figures); repointing
it to `PaymentRequest` is feature work. 35 pages remain on the mock-purge backlog.

---

## Appendix — full classified findings (verified)


### Confirmed P0 — first-test blockers (44)

| # | Domain | Category | Finding | Recommended fix |
|---|---|---|---|---|
| 1 | school-directory | wrong-formula | /schools 'Portfolio at a glance' breakdowns count only first 200 of 700 schools — every Core/Client/Clustered/SSA/Owned number and percentage is wrong | Do NOT derive aggregate counts from a paginated row page. Repoint the strip to the backend's true aggregate: src/app/(shell)/schools/page.tsx — replace liveDirectoryMetrics(liveRows,...) with a call to fetchAnalyticsDashboard(me) (surfaces.ts:121 -> analytics.service.ts:42-57 das |
| 2 | school-directory | mock-leak | /map renders fabricated school + SSA counts from a ~12-row mock with no backend and no isMockAllowed guard | src/app/(shell)/map/page.tsx: make the page async, fetch live counts via fetchSchools(me,{pageSize:200}) for total + an aggregate endpoint (fetchAnalyticsSsa for SSA-done counts), gate behind isBackendEnabled(); when backend off and !isMockAllowed() render an empty/'Insufficient  |
| 3 | school-directory | mock-leak | /districts and /districts/[id] render fabricated district rollups (schools, SSA%, active/inactive, target%) from a static mock with no backend and no guard | Add a backend district-rollup surface (e.g. GET /analytics/districts returning per-district school count + SSA% + cluster% via prisma.school.groupBy(['districtId'])) and repoint both pages to it via a new fetchDistrictRollups(me); fall back to an empty state when backend off and  |
| 4 | clusters | mock-leak | /coverage and /coverage/recommendations render fully fabricated production data, ungated by role | Until a backend coverage service exists, replace the mock-fed body of src/app/(shell)/coverage/page.tsx and recommendations/page.tsx with an 'Insufficient data / coming soon' empty state (DataStates) when !isMockAllowed(); and add a role-restriction entry { prefix: '/coverage', a |
| 5 | ssa-core | mock-leak | /fy/ssa-comparison renders fully fabricated year-over-year SSA numbers in production | Rewrite src/app/(shell)/fy/ssa-comparison/page.tsx to fetch /api/analytics/intervention-improvement (groupBy=district then cluster) like InterventionImprovementGrid.tsx, render EmptyState when not live, and delete the ssa-comparison-mock imports. Until rewired, gate the page body |
| 6 | ssa-impact | mock-leak | /fy/ssa-comparison renders fabricated year-over-year SSA numbers to every logged-in role (no backend, no mock guard) | Replace the page body with the live InterventionImprovementGrid (src/components/ssa/InterventionImprovementGrid.tsx) which already fetches /api/analytics/intervention-improvement and renders an honest empty state when off. Concretely: rewrite src/app/(shell)/fy/ssa-comparison/pag |
| 7 | ssa-impact | mock-leak | /quality-checks and /alerts show hardcoded '876 open issues / 214 critical' to all roles with no backend | These severity counts must come from a real data-quality scan. Short term (before test): gate the mock behind isMockAllowed() and render an empty/'No quality issues recorded' state when false — i.e. in both pages compute critical/major/minor from a backend source or show DataStat |
| 8 | team-partner-plan | mock-leak | /team-targets renders fabricated per-CCEO target rows (non-existent staff) in production mode | Add a backend GET /targets/team in targets.service.ts that, for scope.supervisedStaffIds, runs timePeriod() per supervised staffId and returns per-staff target/achieved; expose via /api/targets/team. In team-targets/page.tsx:39 replace filterStaffForUser+StaffTargetTable with a c |
| 9 | team-partner-plan | mock-leak | /partners 'Established Delivery Partners' shows 5 fabricated partners (4 don't exist in prod) with invented activity counts | Repoint onto live backend: GET /partners list exists (partners.service.ts:87) and per-partner workload via eligible()/_count.activities (partners.service.ts:128-136). Make PartnersIndexClient fetch /api/partners for real names/cert/coverage, and add a list endpoint returning Acti |
| 10 | team-partner-plan | mock-leak | /partners/[id] detail is 100% hand-typed mock (same 3 projects / 14 schools / 78 visits / 64% for every partner) | Resolve the partner by real id from /api/partners, then fetch its real activity rollup (add GET /partners/:id/activities returning partners.service.ts:103 myActivities shape for an arbitrary id, governance-scoped to CD/RVP/IA/PL). Derive Active Projects from distinct projectId, S |
| 11 | team-partner-plan | mock-leak | /team-plan supervision cards use hardcoded org tree + in-memory mock store, not live StaffSupervisorAssignment/Postgres | Make buildTeamPlan async and fetch the team from the backend: add GET /pl/team-plan (or reuse scope.supervisedStaffIds + per-staff timePeriod) returning TeamPlanRow shape. Replace cceosSupervisedBy(hardcoded) with the live StaffSupervisorAssignment-derived list (scope.service res |
| 12 | completed-activities | mock-leak | /trainings renders 100% mock training data (counts, rows, participants) in production mode | Mirror the /visits pattern. Add src/app/api/trainings/route.ts that backendFetch('/activities?pageSize=200') and filters TRAINING_TYPES (training,school_improvement_training,cluster_meeting,cluster_training,core_training,project_activity), mapping status->label and reading teache |
| 13 | completed-activities | mock-leak | /today shows hardcoded COMPLETED/IN-PROGRESS/OVERDUE KPIs + fake week-over-week trends as live data | Replace the static todayDataForRole feed with a backend-derived day. Add src/app/api/today/route.ts (or reuse an existing scoped activities surface) that pulls the caller's activities (?mine=true) and derives COMPLETED=status IN(ia_verified,accountant_confirmed,completed) for the |
| 14 | cost-budget | mock-leak | /budget main dashboard shows a fabricated UGX 116M budget (program+admin) with invented requested/released/burn — real costed plan is UGX 60.7M | Repoint src/app/(shell)/budget/page.tsx off buildBudgetSummary/generateAnnualBudget and onto GET /api/budget/from-schedule (already proxied and live; same surface /budget/breakdown uses via LiveBudgetReport). Have AnnualBudgetDashboard/RvpBudgetSummary/PlBudgetOverview consume th |
| 15 | funds | mock-leak | RVP /approvals shows fabricated 'UGX 18.4B across 12 countries' with fake country/lead list | Repoint RvpFundApprovalsView to backend: replace RvpKpiRow/RvpCountryList mock imports with a live fetch of /api/fund-requests aggregated by submittedByRole/scope (or a new /api/rvp/fund-approvals proxy). Until a regional backend exists, gate the whole view behind isMockAllowed() |
| 16 | funds | mock-leak | All /budget/approvals/* pages render fabricated fund submissions, budgets, amendments and disbursement schedules | These sub-pages duplicate the deprecated hub (the bare /budget/approvals already permanentRedirects to /approvals per page.tsx:13-16). Either (a) permanentRedirect each sub-page to /approvals until a real monthly-country-fund backend exists, or (b) gate each behind isMockAllowed( |
| 17 | funds | mock-leak | /weekly-funds shows fabricated Total Received 510M / Disbursed 284.5M and fake roster to PL/CD/Accountant | /weekly-funds is superseded by /fund-requests (live) + the live FundApprovalQueueLive disburse flow on /approvals. Either redirect /weekly-funds to /fund-requests, or repoint each view: Lead/Accountant KPI rows + queues must read /api/fund-requests (filter status approved/disburs |
| 18 | funds | mock-leak | /monthly-fund-request renders a hardcoded April-2026 mock artifact as the live country fund request (wrong period + fabricated grand total) | No monthly-country-fund backend aggregation exists yet (fund-requests.service.ts handles per-staff monthly only). Until built, gate page.tsx:43-83 behind isMockAllowed(): if false, render <EmptyState title='Monthly country fund request not yet available'/>. When building real: de |
| 19 | funds | mock-leak | /approvals (PL & CD) KPI row + summary + plan detail show fabricated 214.6M/128.4M alongside the live queue | Replace the mock KPI/summary band with values derived from the same /api/fund-requests response FundApprovalQueueLive already fetches (sum totalAmount by status: submitted=Awaiting, approved=Approved, returned=Returned). Remove the FundApprovalQueue queue={liveQueue} + FundPlanDe |
| 20 | accountant | mock-leak | Accountant console renders fabricated financial KPIs in production (UGX 214.8M / 170.4M / 67% utilization) | Remove <AccountantConsoleDashboard/> from src/app/(shell)/dashboards/accountant/page.tsx:92 until its 13 children are repointed to live backend/empty-state. Short term: wrap each accountant-console card body in isMockAllowed() (src/lib/mock-policy.ts) and render <DataStates> empt |
| 21 | accountant | mock-leak | 'Partner Payments Ready to Clear' renders mock requests with non-functional Clear/Return/Hold buttons that falsely confirm payment | Remove <AccountantPartnerPaymentsQueue/> from page.tsx:91 — its function is fully served by the live PartnerPaymentQueue. If a richer ready-to-clear view is wanted, repoint accountantQueue() to /api/payments and wire handleAction to POST /api/payments (clearPayment) like PartnerP |
| 22 | evidence-ia | mock-leak | /quality-checks (and /alerts) show hard-coded 876 'open issues' and mock severity/issue arrays as production data | Either (a) build a real quality-checks backend endpoint (count Activity rows missing salesforceActivityId / awaiting_ia / evidence gaps from Postgres) and fetch it in quality-checks/page.tsx + QualityCheckStatusCard + TopIssuesCard, or (b) until that exists, gate the page body be |
| 23 | hr-leave | mock-leak | /leave dashboard renders fabricated leave numbers in production (18 on leave, 46 days, 27 auto-rescheduled, 4 conflicts, 8 fake staff) while Leave table is empty | Repoint each card off leave-mock onto live backend or render an empty/insufficient-data state. Minimal P0 fix: in each component, gate the mock arrays behind isMockAllowed() and otherwise render the DataStates empty primitive (e.g. LeaveKpiRow.tsx:29 → const src = isMockAllowed() |
| 24 | staff-performance | mock-leak | /team-targets Fair Workload Index renders fabricated named-staff performance bands with NO guard (hard mock leak) | Repoint the Fair Matrix to the real backend. Add an /api proxy for GET /leadership/decision-engine?decisionType=staff_hr (proxy dir already exists: src/app/api/leadership/[...path]/route.ts) and build a server component that maps each staff_hr insight's metrics {rawAchievement, a |
| 25 | staff-performance | mock-leak | Director dashboard 'Staff Performance Summary' (avg achievement, risk counts, PIP watchlist) is fabricated mock data | Convert StaffPerformanceSummary to a server component that fetches the staff_hr board (DecisionEngineEmbed already does this pattern) or fetchHrRoster + targets, and derive counts from real rows. As an immediate stop-leak, wrap the component body so that when !isMockAllowed() it  |
| 26 | partner-performance | mock-leak | /partners and /partners/[id] render entirely fabricated partner data (wrong names, wrong IDs, wrong metrics) in production | Repoint /partners index to the live backend list: server-fetch via fetchPartners(user, false) (src/lib/api/surfaces.ts:954, which hits GET /partners) and pass real BePartner[] (id, name, expertiseAreas, activeStatus, certificationStatus) into PartnersIndexClient instead of partne |
| 27 | partner-performance | mock-leak | /dashboards/partner Command Center is 100% mock — every metric, count, payment and impact figure is fabricated in production | The real per-partner numbers already exist server-side: PartnerPerformanceService.computeAll (partner-performance.service.ts) for assigned/completed/evidence/IA/overdue/reschedule/capacity, and /partners/me/activities (surfaces.ts:1059 fetchMyPartnerActivities) for the caller's o |
| 28 | partner-performance | mock-leak | /partner/inbox/[tab], /partner/activities, /partner/payments show hardcoded KPI literals contradicting the DB | Repoint all three to the live partner activity list (fetchMyPartnerActivities / GET /partners/me/activities). Compute the inbox tab counts, the My Activities KPI tiles (total/active/overdue/completed-this-month) and the payment ledger rows from the returned Activities (status, sc |
| 29 | decision-engine | mock-leak | /decisions renders FABRICATED leadership recommendations (named staff, fake workloads, fake costs) in production — no backend, no mock guard | Repoint /decisions onto the live engine exactly like /analytics/decision-engine. In src/app/(shell)/decisions/page.tsx: replace the decisions-mock + field-intelligence-mock imports with fetchLeadershipBoards/fetchLeadershipSnapshot from @/lib/api/surfaces (the same calls Decision |
| 30 | donor-metrics | mock-leak | Entire donor reporting surface renders hardcoded fabricated numbers in production — not derived from any record | Wire src/lib/donor-metrics.ts:81 scopeShape() to a real backend aggregate. Add analytics.service.ts donorSnapshot(user) (../edify-api/src/modules/analytics/analytics.service.ts) that, scoped by user.schoolIds, runs: teachersTrained=SUM(Activity.teachersAttended) WHERE status IN ( |
| 31 | analytics-reports | mock-leak | Entire /analytics body (charts, heatmap, data-quality, CSV export) is computed from a 12-school mock universe, contradicting the live band on the same page by 10x | Repoint computeAnalytics onto backend data: replace the mock-array imports in src/lib/analytics/compute-analytics.ts:11-20 with a server-fetched record set passed into ComputeInput (the page already fetches scoped backend data via surfaces.ts — pass activities/SSA/schools from ed |
| 32 | analytics-reports | mock-leak | /field-intelligence renders all 6 KPIs + weekly reflection from hardcoded mock debriefs (date 2025-11-12), not the live DailyDebrief backend | In src/app/(shell)/field-intelligence/page.tsx replace the field-intelligence-mock calls (lines 27-36) with a fetch of today's debrief + weekly rollup from the DailyDebrief backend (via an /api/debriefs proxy / DebriefsService.today). Until wired, guard the KPI row + cards behind |
| 33 | role-dashboards | mock-leak | CommandStack action rail renders hardcoded mock (Next-3-actions, inbox, change digest) on 8 role dashboards with no backend or mock guard | In src/components/actions/CommandStack.tsx, gate the mock board: when !isMockAllowed() (mock-policy.ts), do not render board.nextThree/inbox/changedSince/doneToday from buildRoleActionBoard; instead drive them from the live /api/command-center/today feed (already fetched by Today |
| 34 | role-dashboards | mock-leak | Accountant console KPI strip + money cards show hardcoded UGX figures and 'May 2025' period — fake production finance data on the finance role's primary dashboard | Repoint AccountantConsoleDashboard (KpiStrip, DisbursementSummary, DisbursementsByCategory, FundsReceivedTable, RecentDisbursementsList) onto live finance endpoints (PaymentRequest/FundRequest/Disbursement aggregates via a new /api/accountant/* proxy or extend analytics). Until w |
| 35 | role-dashboards | mock-leak | Accountant Payment Pipeline funnel reads the in-memory demo seed store, not Postgres — shows 2 IA-verified / 0 paid instead of ~118 paid | Replace paymentPipelineStages() store reads with live Postgres-backed counts via a proxy (e.g. /api/payments aggregates already exist for PartnerPaymentQueue) — count Activity by paymentStatus (ia_confirmed/netsuite_accountability/paid/closed) and PaymentRequest by status. Remove |
| 36 | role-dashboards | mock-leak | Director Country Mission Control KPI row shows 28,450 schools / 154 pending fund requests / UGX 5.29B — fabricated, sits next to live ~700-school card | Replace CountryKpiRow's countryKpis with live analytics (fetchAnalyticsDashboard already returns scoped school/core/ready/ssa counts; extend for fund + SF compliance) or guard with isMockAllowed() and hide when false. Same for MissionSnapshotStrip/DonorImpactReachCard which consu |
| 37 | role-dashboards | mock-leak | RVP Regional Signals + Country Comparison invent 4 countries (545 schools, UGX 2.5B committed) — production has 1 country / 700 schools | Drive RVP Regional Signals + Country Comparison from live country-scoped analytics (backend analytics.service.ts:37-39 aggregateSchoolWhere already supports RVP country-wide counts). Guard countryRollups behind isMockAllowed(). rvp/country-summary/page.tsx is fully mock (rvpCount |
| 38 | role-dashboards | mock-leak | Project-Coordinator KPI row hardcodes 'Schools in Projects=426' and floors Partners to 16; closing-period filter pinned to 2025-05 | Compute SpKpiRow from the real Project/ProjectSchoolAssignment/ProjectPartnerAssignment tables via a backend proxy (SpecialProjectsLiveBoard already fetches projects — extend it to emit the KPI aggregates). Remove the literal 426, Math.max floor, and the hardcoded 2025-05 period; |
| 39 | role-dashboards | role-scope | Partner dashboard is fully mock and unscoped — every partner sees identical fake totals (assigned 7 / paid 16); own-only scoping seam absent | Repoint the partner dashboard onto the live, org-scoped partner surface (the bridge maps partner roles → org; /api/partners/me/activities exists per memory). Replace the flat mock constants with a fetch scoped to the caller's partnerId, and render DataStates empty when backend of |
| 40 | period-fy | wrong-formula | Period rollup buckets activities by an UNVALIDATED stored quarter column that is wrong for every seeded activity — Mid-Year shows 243 done when truth is 0 | targets.service.ts: stop trusting Activity.quarter. (1) Add `scheduledDate` to the select at targets.service.ts:120, and at line 160 bucket by date: `const inP = acts.filter(a => { const q = quarterOfDate(a.scheduledDate); return q && p.quarters.includes(q); });` (mirror the SSA  |
| 41 | notifications-messages | mock-leak | Partner message center renders fabricated mock threads/counts in production (no backend, no isMockAllowed guard) | Repoint the partner surface onto the live backend exactly like the internal one was migrated. (a) src/app/(shell)/partner/messages/page.tsx: replace messagesForUser()/MessageCenterLayout with the same <LiveInbox/> used at src/app/(shell)/messages/page.tsx:51 (it fetches /api/mess |
| 42 | target-achievement | mock-leak | /team-targets renders fabricated CCEO + team operating-target numbers in production (no mock guard, no backend) | Replace the OperatingTargetsView mock feeds on /team-targets with backend-driven data: drive the CCEO 'My Targets' slot and the team slot from /targets/summary + /targets/time-period (per supervised staffId) instead of cceoOperatingTargets/teamOperatingTargets. As an immediate st |
| 43 | target-achievement | mock-leak | Partner target table shows fake partners (Amref/World Vision/Plan Intl) with invented achievement % on /team-targets | Repoint PartnerTargetTable to a live source (BE partner-assigned activity rollup scoped to the viewer's org/supervision) or gate behind isMockAllowed() and render EmptyState in prod. Same treatment for StaffTargetTable (page.tsx:124, filterStaffForUser from team-targets-mock) and |
| 44 | target-achievement | mock-leak | Per-staff target rows + Fair Workload matrix on /team-targets are fabricated (filterStaffForUser, fwi-mock) | Gate StaffTargetTable, FairMatrixPlot, and RebalanceRecommendationsCard behind isMockAllowed() in team-targets/page.tsx and render DataStates EmptyState in prod; long-term, derive per-staff target progress from /targets/summary?staffId=<supervised> looped over scope.supervisedSta |

### Confirmed P1 — must fix before external testing (46)

| # | Domain | Category | Finding | Recommended fix |
|---|---|---|---|---|
| 1 | school-directory | mock-leak | /fy/gateway planning-lock counts come from a mock summary set, never the 700 real schools | Repoint /fy/gateway to live: derive lock levels from fetchSchools planningReadiness/currentFySsaStatus aggregates (or a /planning/setup buckets call which already exists, surfaces.ts:781), gate behind isBackendEnabled, empty-state when off and !isMockAllowed. Lower than P0 becaus |
| 2 | clusters | mock-leak | /clusters readiness card + unclustered banner show mock counts (0 clustered / 20 unclustered) vs live 288 clustered / 37 clusters | Make the readiness counts live: add a backend cluster-counts surface (e.g. extend clusters.service.ts with a counts() returning clustered/unclustered/needsReview from School where clusterStatus grouped, district-scoped) and a /api/clusters/counts proxy; in src/app/(shell)/cluster |
| 3 | clusters | wrong-formula | Cluster detail Avg-SSA shown as % of a 0–10 score, SSA-Completed always 0/N, SSA badge prints raw enum | In ClusterMemberSchoolsLive.tsx: (1) render Avg SSA as a /10 score not %: value=`${avgSsa}` (or `${avgSsa}/10`), and set tone thresholds on the 0–10 scale (e.g. >=7 green, >=5 amber); line 130 → ` · SSA ${s.latestSsa}` (no %). (2) Fix completed to s.ssaStatus==='done' (line 62).  |
| 4 | clusters | wrong-formula | Every cluster falsely reports 'no SIT' gap because school_improvement_training activities have Activity.clusterId NULL | Backfill Activity.clusterId from the activity's school.clusterId for cluster-type activities (one-off data migration + ensure the activity-create/schedule path sets clusterId for school_improvement_training/cluster_meeting). Alternatively, in clusters.service.ts:134 broaden the a |
| 5 | ssa-core | wrong-formula | Two-weakest interventions ('plan these') has no deterministic tie-break and is rendered to users | Add a deterministic tiebreaker wherever weakest-N is sliced: .sort((a,b)=> a.score-b.score \|\| a.intervention.localeCompare(b.intervention)). Mirror in ssa.service.ts:63, core-candidates.ts:27, cluster-meeting-recommendations.ts:108. Add orderBy:{intervention:'asc'} to the score |
| 6 | ssa-core | period | Per-school recommendation + 'plan these' use latest-by-date SSA across all FYs, not latest current-FY | In ssa.service.ts:56-60 select the latest record where fy===getOperationalFY() AND scores.length===8; if none, return hasSsa:false / 'No current-FY SSA - planning locked'. Surface fy to the drawer so SchoolSsaLive picks the latest current-FY complete record or shows the locked/st |
| 7 | ssa-core | wrong-formula | Four divergent severity formulas; BE miscuts Critical at <4 and has no Strong band | Adopt one canonical classifySeverity (<5 Critical, <7 Needs Support, <9 Good, else Strong; struggling=score<7) imported everywhere. Fix ssa.service.ts:66 to minScore<5?'critical':minScore<7?'support':minScore<9?'good':'strong'. Replace orphan severityBand and align SchoolSsaLive  |
| 8 | ssa-impact | mock-leak | IA dashboard renders fabricated KPI row / Top Issues / Partner cards beside live SSA grids | Repoint the impact dashboard mock cards to live data or guard them. ImpactKpiRow should derive its 5 KPIs from a backend M&E/verification summary (EvidenceRecord/PaymentRequest/SsaRecord counts) instead of impact-mock.impactKpis; TopIssuesCard/PartnerPerformanceCard/RecentDataUpl |
| 9 | ssa-impact | mock-leak | Donor reporting print + leadership donor cards render mock impact/reach figures (Year-1 mock-backed lib) | Primary owner is the donor-metrics domain, but for the SSA-impact slice: derive the SSA reach/improvement portion of the donor snapshot from the live analytics services (ssaPerformance + interventionImprovement) rather than donor-metrics constants, and gate the print page behind  |
| 10 | planning-gaps | wrong-formula | Planning gap boards render at most 8 schools per bucket; real backend count (up to 412) is dropped — CD/Admin see a massively understated gap board | Two-part: (1) Surface the true count. Thread bucket.count through: change backendSchoolGaps to return {gaps, counts} or pass each bucket's count into the board so the collapsible header badge shows backend count not list.length (SchoolGapsBoard.tsx:428 should render a prop count, |
| 11 | planning-gaps | wrong-formula | /planning Core Schools tab labels every core school 'No Visit' (Visit 1) even when Visit 1/Training 1 are already complete — wrong next action for 39 schools | Drive the Core tab from the slot-aware corePlanning() endpoint instead of the flat coreSchoolPlanning setup bucket. Either (a) point the Core tab at fetchPlanningCore (surfaces.ts:784 -> /planning/core) and render the per-slot sections (missingVisit1..4/missingTraining1..4) the C |
| 12 | planning-gaps | period | 490 SsaRecords carry fy='2025' for dates that are operationally FY2026; any cluster-assign or SSA-upload triggers recompute() which would demote all 81 'Ready to Plan' schools to 'No SSA' | Data fix (primary): correct the mislabeled fy on existing records so it equals the operational FY of dateOfSsa: UPDATE "SsaRecord" SET fy='2026' WHERE "dateOfSsa" >= '2025-10-01' AND "dateOfSsa" < '2026-10-01' AND fy <> '2026'; (re-seed should use getOperationalFY(dateOfSsa), not |
| 13 | my-plan | period | Overdue school visits are bucketed as 'Planned This Week/Month' and never flagged overdue | In sectionMyPlan (src/lib/planning/my-plan-sections.ts:327-348) add an overdue branch BEFORE the exactDate dueToday check: for any item with a concrete dateIso where date < todayIso, route to dueToday (or a dedicated 'overdue' surface) regardless of exactDate — a visit with a rea |
| 14 | my-plan | period | No-date items in a future plannedMonth land in 'Planned This Month' (June) instead of their real month | Pass the item's plannedMonth into MyPlanItem (add field in fromBeActivity ~:216) and in sectionMyPlan gate the thisMonth bucket on plannedMonth === today's month; items whose plannedMonth/date are in a later month should route to a 'Later' lane or be excluded from 'This Month'. A |
| 15 | my-plan | handoff | Partner-uploaded evidence pending the CCEO's review is not surfaced in 'Waiting on Me' | In fromBeActivity (src/lib/planning/my-plan-sections.ts:203-207) add 'uploaded' to the evidence waitingOn trigger ONLY for partner-delivered rows (a.deliveryType==='partner' && ev==='uploaded') so partner evidence awaiting CCEO acceptance routes to waitingOnMe with nextAction upl |
| 16 | team-partner-plan | mock-leak | 'What Needs Attention' strip + Team operating rollup are impossible fabricated aggregates | Remove AttentionStrip + OperatingTargetsView(teamData) + FairMatrixPlot/RebalanceRecommendationsCard (all fwi-mock) from the production team-targets render, or gate the entire mock surface behind isMockAllowed(). Replace with aggregates from the live /targets/team endpoint (super |
| 17 | team-partner-plan | wrong-formula | TargetsLive titled 'Team target progress' actually shows the caller's OWN targets (no team-sum endpoint) | Either (a) add a true team aggregation endpoint summing timePeriod over scope.supervisedStaffIds and feed TargetsLive from it, or (b) rename the card to 'My target progress' for PL until the team endpoint exists. Do not present a single-staff computation under a 'Team' label. |
| 18 | completed-activities | mock-leak | Impact dashboard TrainingDataQualityCard invents a 70/20/10 evidence split from a 3-row mock instead of EvidenceRecord | Repoint TrainingDataQualityCard to a backend surface that joins training-kind activities to EvidenceRecord (evidenceStatus accepted vs uploaded vs returned/contested) and iaVerificationStatus. Replace the 0.70/0.20/0.10 arithmetic in training-stats.ts:124-126 with real counts: wi |
| 19 | cost-budget | wrong-formula | Cluster meeting costed FLAT (300k) by backend but PER-PARTICIPANT (400k) by FE — 100k gap on the same activity; violates the 'by participant count' spec | Pick ONE semantics and make both engines agree. Per the spec, change costing.ts:95-96 to add('Cluster meeting per participant','cluster_meeting_per_participant', participantsOf(a)) and seed that CostSetting key, OR (if flat is intended) change the FE cluster-meeting calculators t |
| 20 | cost-budget | stale-after-action | No cost snapshot: a CD rate change retroactively re-prices ALL historical/completed activities (ActivityBudgetLine never written) | On schedule/commit, write an ActivityBudgetLine snapshot (costSettingKey, unitCost, qty, amount, version) per activity; in fromSchedule/breakdown/weekly read the snapshotted line when present and only fall back to live rateCard() for not-yet-snapshotted activities. This makes ver |
| 21 | cost-budget | wrong-formula | Staff-visit secondary-district transport rate is never applied in any budget rollup (districtType not resolved); and the seeded secondary rate is LOWER than primary | In fromSchedule/breakdown/weekly select responsibleStaff.staffProfile.primaryDistrictId and school.districtId, derive districtType = (equal ? 'primary' : 'secondary'), and pass it into costForActivity. Fix the seeded rate so secondary >= primary (align to FE 66k vs 56k or correct |
| 22 | cost-budget | mock-leak | Scheduling drawer prices NEW activities from hardcoded FE constants, not the live CD rate card — schedule-time cost diverges from the actual budget | Replace the local compute in ScheduleActivityDrawer.tsx:216-221 with a fetch to POST /api/costing/preview (activityType, deliveryType, districtType, participant counts); show backend amount + costMissing; only fall back to the local estimate when {live:false}. This is the same pa |
| 23 | accountant | mock-leak | Payment Pipeline funnel on accountant dashboard reads in-memory mock store, not backend | Replace paymentPipelineStages() with a live fetch: derive the 5 stages from the backend (extend a new /api/payments/funnel proxy over an activities-service aggregate of paymentStatus counts: ia_confirmed→toAccountant, accountant_cleared→cleared, netsuite_accountability+netsuiteEx |
| 24 | accountant | stale-after-action | Staff NetSuite Accountability queue shows fabricated rows; close-out writes mock store, hiding 5 real activities | Build a live staff-accountability surface: backend activities-service query (deliveryType=staff, paymentStatus=netsuite_accountability) + a closeAccountability(id, netsuiteId) endpoint that validates the NetSuite ID (3-6 digits) and persists netsuiteExpenseId + paymentStatus='clo |
| 25 | accountant | validation | Accountant clears partner payment without seeing the amount; amount never reconciled to PaymentRequest/budget line | Add the payable amount to paymentQueue: join PaymentRequest (or compute from cost catalogue) and include amount in the select + BePaymentQueueRow; render it per row in PartnerPaymentQueue. In clearPayment, record the cleared amount (write a PaymentDisbursement row, see finding pa |
| 26 | accountant | handoff | clearPayment writes no PaymentDisbursement/PaymentActionLog; PaymentRequest tables orphaned and out of sync with Activity.paymentStatus | In clearPayment, after the paymentStatus update, in the same $transaction: upsert/update the PaymentRequest (status='paid'), insert a PaymentDisbursement (paymentRequestId, amount, clearedBy=user.userId, reference) — the UNIQUE paymentRequestId then enforces no duplicate disburse |
| 27 | accountant | mock-leak | /partner/payments header shows hardcoded fake payment KPIs (UGX 5.6M paid / 3.5M in flight) | Derive the partner-payments KPIs from the partner's own backend activity payment states (extend /partners/me/activities or a /api/partner/payments aggregate) and PartnerPaymentStatusCard from live data; render empty/Insufficient-data when backend off. (Cross-domain with partner a |
| 28 | hr-leave | wrong-formula | Approved-leave conflict detection queries the empty MonthlyPlanActivity table (and with an incompatible date format) — real scheduled activities on leave days are NEVER flagged | Rewrite the conflict scan in hr.service.ts:133 to query the Activity table by responsibleStaffId and date-prefix match, e.g. count Activity where responsibleStaffId = leave.staffProfileId, status notIn ['completed','cancelled'], and the date portion of scheduledDate is in leaveDa |
| 29 | hr-leave | mock-leak | HR dashboard KPI strip + Attention banners + Aggregated Field Context are hardcoded/mock and shown unguarded in production | Replace HrKpiStrip literals with values derived from the live roster (/hr/roster already returns counts.total/active/pending — surface those) plus a leave count from /hr/leave; render '—' or an empty state where no backend metric exists yet. Make HR_ALERTS counts derive from the  |
| 30 | staff-performance | role-scope | /team-targets has no role restriction — any authenticated role can view named-staff PIP/early-warning bands | Add a restriction entry in src/middleware.ts (the prefix/allow list near line 268): `{ prefix: "/team-targets", allow: ["CountryProgramLead","CountryDirector","RVP","HumanResource","ImpactAssessment","Admin"] }`. Keep CCEO out (they have /my-targets for self-view); the page's def |
| 31 | staff-performance | stale-after-action | Context-fairness pipeline never populated — StaffContextProfile=0 and LeadershipDecisionInsight=0, so the REAL context-aware staff board is empty in prod | Run the recompute before the test: POST /api/leadership/decision-engine/recompute as an LEADERSHIP_DECISION_REVIEW role (CD/RVP/HR/Admin) for fy 2026, or add it to the seed/migrate-deploy step. Verify with psql: select count(*) from "StaffContextProfile"; and select decisionType, |
| 32 | staff-performance | mock-leak | HR dashboard 'attention' banners show hardcoded counts (3 decisions / 4 flagged / 6 reviews due) | Derive the counts from the live staff_hr board (count insights with riskLevel high / riskFlags 'low-achievement') and the routed-debrief/review queues, or remove the hardcoded numerals and use generic copy ('Open decisions','Review flagged staff') until wired. Do not present fabr |
| 33 | partner-performance | stale-after-action | PartnerPerformanceProfile and LeadershipDecisionInsight are empty in prod — the one correct partner board renders nothing until a manual recompute | Run the recompute once as part of seed/migrate so the board is populated for the test (call leadershipEngine.recompute(getOperationalFY()) in the gated seed, mirroring how budget intelligence is recomputed), OR add an empty-board hint that auto-offers Recompute. At minimum, ensur |
| 34 | decision-engine | stale-after-action | Live decision boards are EMPTY in prod — recompute() has never populated LeadershipDecisionInsight, so the real engine surfaces show nothing | Run a recompute against the seed so the live boards are populated for the test: authenticated POST to /api/leadership/decision-engine/recompute (CD/RVP/HR/PL/Admin per CAN_RECOMPUTE in analytics/decision-engine/page.tsx:16), or call LeadershipEngineService.recompute(getOperationa |
| 35 | donor-metrics | period | Reporting period / cycle filter is displayed but never applied to any metric | When the backend snapshot is wired, pass dateRangeStart/dateRangeEnd (and fy/quarter) into the aggregate WHERE clause (Activity.scheduledDate BETWEEN, or Activity.fy/quarter) at the new donorSnapshot() query. Until then, remove the period/cycle stamp from the CSV preamble (route. |
| 36 | donor-metrics | validation | Fabricated 'students impacted under-counted: N schools missing enrollment' warning fires when DB has 100% enrollment coverage | In the new backend donorSnapshot(), compute schoolsWithEnrollment/schoolsReachedTotal from the real reached set (COUNT where School.enrollment IS NOT NULL AND >0). The warning at donor-metrics.ts:682, the 'estimated' tag at L300/L626, and the coverage card then reflect actual cov |
| 37 | donor-metrics | wrong-formula | Intervention and district breakdown tables and CSV exports are weight/triangular-distribution math over fabricated totals, not GROUP BY | Replace buildInterventions (donor-metrics.ts:778) with GROUP BY Activity.purposeIntervention (joined to the SsaInterventionArea taxonomy) and buildDistricts (L800) with GROUP BY School.districtId over the real reached set, both backend-computed. Remove the *1.3 inflation (L792) a |
| 38 | analytics-reports | mock-leak | RVP country-summary, HR field-intelligence card, and /decisions board render mock aggregated leadership intelligence with no backend and no guard | Repoint these onto the DailyDebrief/LeadershipDecisionInsight backend (LeadershipDecisionInsight table is currently empty=0 per seed, so the honest prod state is empty). Short term: wrap the AggregatedFieldContextCard / DecisionCard sections in isMockAllowed() and show EmptyState |
| 39 | role-dashboards | mock-leak | HR KPI strip and HR Attention banners are hardcoded AND disagree with each other (12 vs 6 reviews) | Drive HrKpiStrip and HR_ALERTS from a single live HR source (extend /api/hr; staff/leave counts already available via fetchHrRoster). Eliminate the duplicate hardcoded count so the strip and banner cannot diverge. Guard with isMockAllowed() until wired. |
| 40 | period-fy | period | reschedule() updates scheduledDate but never recomputes quarter/fy — a rescheduled activity counts in the OLD period | In activities.service.ts reschedule() data block (~:236), recompute period fields from the new date: add `quarter: quarterOfDate(new Date(dto.scheduledDate)) ?? undefined, fy: getOperationalFY(new Date(dto.scheduledDate))` (import quarterOfDate from targets-config and getOperatio |
| 41 | period-fy | validation | Activity create() accepts client-supplied quarter/fy with no derivation or validation against scheduledDate | Derive server-side and ignore client quarter/fy: at activities.service.ts:103 set `quarter: dto.scheduledDate ? quarterOfDate(new Date(dto.scheduledDate)) : dto.quarter` and `fy: dto.scheduledDate ? getOperationalFY(new Date(dto.scheduledDate)) : dto.fy`. Or add a validation guar |
| 42 | period-fy | period | FE engine clock (Nov 15 2025) and BE seed data clock (Jun 12 2026) are 7 months apart — FE 'expected-by-now'/pace is computed for Q1 against Q3 backend data | Pick ONE clock truth for the demo. Either (a) move the FE engine clock forward to match the seed (clock.ts:14 → a June-2026 date) so elapsedFraction and 'current week/month' align with the data, or (b) re-seed scheduledDate relative to the FE engine now (Nov 15 2025) so the data  |
| 43 | notifications-messages | stale-after-action | Partner message read/acknowledge/resolve/archive write to in-memory mock store, not the backend — counts never persist after the action | Once the partner surface uses LiveThread (see partner-messages-hard-mock-leak), mark-read is handled server-side by messages.service.thread() (messages.service.ts: updateMany status unread→read for caller). Remove status-actions.ts mock usage. If per-recipient ack/resolve/archive |
| 44 | notifications-messages | mock-leak | Partner compose + reply persist to the mock store via appendMessage/appendReply; messages never reach a real recipient | Rewrite sendMessageAction/replyMessageAction to POST to /api/messages and /api/messages/[id]/reply (the same endpoints the internal LiveCompose uses), which are backend-wired (messages.service.send/reply, with role-scoped recipients() and participant checks). Drop the appendMessa |
| 45 | target-achievement | validation | Live targets count 'completed' (unverified) as achievement, contradicting the documented verified-only rule | Decide and apply the achievement basis consistently. If verified-only is intended (per spec + target-counting.ts + memory id-consistency-verification): change targets-config.ts:6 to DONE_STATUSES=['ia_verified','accountant_confirmed'] and add a separate FIELD_COMPLETE set for pro |
| 46 | target-achievement | role-scope | PL 'Team target progress' card shows the PL's own portfolio, not supervised CCEOs | Add a BE /targets/team endpoint that loops scope.supervisedStaffIds (already resolved in scope.service.ts:86) and sums per-staff timePeriod cells, then point the PL/CD/RVP 'Team target progress' card at it. Until then, retitle the existing card 'My target progress' so it is not p |
