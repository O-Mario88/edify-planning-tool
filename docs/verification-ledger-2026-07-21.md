# Post-remediation verification audit — findings

Baseline: HEAD 58e107b5 → 8257a7c2. Py 3.13.12, Django 5.2.4, PostgreSQL 16.13.
Full suite 1866 OK at 8257a7c2.

## HARD GATES ALREADY RED (§48 automatic no-go)

**G1. Scheduler disabled.** `ENABLE_BACKGROUND_JOBS` defaults False
(config/settings/base.py:285); docker-compose.yml declares NO worker service —
only Procfile has `worker: python manage.py runscheduler`. §48 lists
"Scheduler disabled" as automatic NOT READY.

**G2. Lint/format gate.** ruff: 22 errors at audit start (18 pre-dating the
uncommitted work), 65 files unformatted. §45 requires 0 of each.

**G3. TWO RUNTIME BUGS IN MY OWN FIXES** — found by ruff F821, NOT by the
1866-test suite, because no test exercised those lines:
  - `finance_views.py:1000` — `MonthlyFundAllocationService` undefined in the
    drilldown scope guard I added → NameError on first request.
  - `messaging/services.py:1235` — `sender` undefined in the linked-item
    authorisation I added → NameError on any send with linkedItems.
  Both fixed; source-inspection tests replaced with RUNTIME tests.
  LESSON: assertions that read source text cannot see an undefined name.

## TRACK: SSA / entitlements (agent V-SSA) — CRITICAL

**C1. Cluster training credit gate is a status nothing writes.**
`view_models.py:89`, `planning_service.py:521`, `clusters/services.py:513` gate
on `status="completed"`. Verified every production `Activity.status` assignment:
the live set is completion_started, submitted_to_pl, awaiting_ia_verification,
ia_verified, returned, returned_by_ia, closed, partner_scheduled, planned,
rescheduled, assigned_to_partner, cancelled, deferred. `"completed"` is written
ONLY by seed.py:656. So an evidenced + SF-stamped + IA-verified cluster training
credits NOBODY, while 260 seeded rows (sf_id None, evidence none, IA pending)
credit EVERYBODY listed.

**C2. Unverified SSA drives live recommendations.** SQL WHERE proven — no
`verification_status='confirmed'` filter at: planning_views.py:1004
(intelligence panel), :499 (schedule modal), :1309 (assign-partner form),
projects/planning_service.py:248. Projects CSV export ships it
(extended_views.py:1598).

**C3. Client entitlement (1 visit + 1 training/FY) has NO enforcement.**
Guard removed; activities/services.py:417-424 documents the removal. Only a
stale detector remains (system_health/services.py:761) whose comment claims the
opposite. DATA: 3 client schools already breach in FY2026 (S-1114, S-1418, DBG-P).

**C4. Core 2+2 staff cap ABSENT (not advisory).** core_planning_services.py:200
checks fy+quarter+delivery_type with visit/training as separate counters →
1 staff visit + 1 staff training per quarter × 4 = 4+4 staff-deliverable, zero
for partners. The "2 Partner / 2 Staff" split is a computed label at :1411 that
is NEVER RENDERED.

**C5. Non-member schools creditable on cluster activities.**
`attended_school_ids` is `ArrayField(CharField)` with no FK, no constraint, no
server-side membership check (my_plan_views.py:1285 forwards POST unfiltered).
IA's review workspace iterates real members, so an injected id renders nowhere
yet counts everywhere.

### HIGH (same track)
- **18 competing weakest-intervention implementations.** Measured disagreement
  vs canonical on real schools: setup 18.5%, plan_builder 42%, clusters 13.3%,
  projects 31%. 13 of 18 have no tie-break → non-deterministic.
- **Core FY rollover is a hard stop.** `CorePlan.school_id` unique with no FY in
  the key. On 1 Oct 2026 every Core drawer raises "no active core package".
- **Core cap bypassable** by POSTing `activity_type=core_visit` to
  /planning/schedule-action → planning/services.py:534 → create(), no slot check.
- **Champion pathway unreachable** — assessment slot 9 has no write path
  (`assert_can_schedule` rejects non visit/training), so completed_slots caps at
  8 against a >=9 test.
- **Champion eligibility scored off unverified SSA** (champion_services.py:22,34,46).
- **Cluster meetings counted as school trainings** (view_models.py:88),
  contradicting activity_types.py:60-73 by name.

### DATA INTEGRITY (dev DB, measured)
- 222 of 325 CorePlans are ORPHANS — school_id matches no School row.
- `CoreActivitySlot.status` has two casings: 'Planned' 2101 / 'planned' 824.
- `Activity.status` holds 100 rows of `'verified'` — NOT a member of ActivityStatus.
- 394 of 700 schools (56%) have newest confirmed SSA in FY2025 while
  operational FY is 2026.

### VERIFIED CORRECT (this track)
- Enrolment COUNT vs SCORE never conflated — proven on 400 records, 0 equal,
  separate header maps, SSA path writes only SsaRecord.new_enrollment.
- Missing SSA → Baseline recommendation, nothing fabricated (executed).
- Canonical engine itself is sound: confirmed-only, min-N honesty,
  deterministic sort, bands via ssa_score_band, cluster-bounded peers.
- Core 9-slot generation correct in data: all 325 plans exactly 9, split 1/4/4.
- Reschedule reuses the same Activity.

## FIX PASS (this session, post-restart)

DONE:
- G2 lint/format: ruff 0 errors, whole repo formatted (65 files).
- G3 runtime NameErrors: both fixed + runtime tests replacing source-inspection.
- C1 phantom status: COMPLETED_WORK_STATUSES in apps/core/activity_types.py;
  45 kwarg sites + 7 python-side comparisons swept across 15 files; the two
  training-fulfilment tallies use IA_VERIFIED_STATUSES strictly and drop
  cluster_meeting from the trainings count.
- C2 unverified SSA: verification_status="confirmed" added at planning_views
  (3 sites), projects/planning_service prefetch, champion_services (3 sites).
- C3 client entitlement: _assert_schedule_entitlement in activities.create() —
  one visit + one training family per client school per FY; cancelled/rejected/
  deferred release the slot.
- C4 core 2+2: STAFF_ANNUAL_CAP=2 per type per FY in assert_can_schedule,
  checked before the quarter window.
- Core bypass: create() refuses core_visit/core_training without
  coreSlotVerified; both legit call sites in core_schools_views set it after
  locking the slot.
- C5 attendance: _cluster_member_school_ids() filters + dedupes at both
  writers (record_attendance + complete).
- G1 scheduler: dedicated `worker` service added to docker-compose.yml running
  runscheduler with ENABLE_BACKGROUND_JOBS=true.
- Tests: apps/core/tests/test_verification_criticals.py — 12 behavioural
  regressions, all green.

STILL OPEN (from V-SSA, not yet fixed):
- 18 competing weakest-intervention implementations (consolidation deferred —
  the four live surfaces now at least read confirmed-only data).
- Core FY rollover hard stop (CorePlan.school_id unique, no FY in key/ids) —
  needs a migration + id-scheme decision; breaks 1 Oct 2026.
- Champion 9th slot unreachable (assessment slot has no write path).
- Data repair: 222 orphan CorePlans, 100 'verified' status rows, 2 slot-status
  casings, 394 stale-FY SSA schools.
- 7 verification tracks (authz, finance-reconciliation, scope, planning/
  closure/targets, projects/partner/leadership, navigation/dashboards,
  automation) died with the process restart — not re-run.

## RELAUNCHED TRACK VERDICTS (compact)

FINANCE: planned→requested seam = UGX 0 (13,152,000 both sides); nothing yet
disbursed in dev. pay_partner safe via uniq_partner_payment_per_activity
constraint (not via lock — caveat noted). Reconciliation identities: canonical
signed-variance form in advance_service (:278,:434,_reconciliation_ok :372);
legacy duplicate in finance_services.py:491 (System A, review-only).
FIXED THIS PASS: disburse_reimbursement had NO idempotency guard (the only
unguarded money path) → now select_for_update + paid-check inside atomic,
with a behavioural regression. OPEN: cross-channel check-then-act race in
pay_partner (LOW); one seed-corrupt AdvanceRequest row (MED, data).

AUTHZ: page/direct-URL parity PASS across the 6 most sensitive keys + API
siblings. Flags PASS (explicit permission + row-scoping). FIXED THIS PASS:
frontend SSA upload+commit now require Permission.SSA_UPLOAD — page-only
gating let CD/RVP/PL/CCEO mint auto-confirmed SSA (staff uploads are born
"confirmed"), violating the IA-authority hard gate. OPEN: Permission.EXPORT
enforced by only 1 of ~20 CSV endpoints (MED — wire can_export or retire it);
HR roster API predicate differs from page gate (LOW).

## TIER 2-3 PROGRESS (2026-07-22)

TRACK VERDICTS (rerun): closure/targets PASS (0 dup credits, 0 calendar bugs,
0 zero-cost lines); projects/leadership ENFORCED (pause/close blocks planning
at create(); CD injection blocked) after fixing review() scope + partner
notification resolution; navigation PASS (236/236 links, 9/9 KPIs exact);
scope track: all previously-fixed leaks CLOSED except two of my own fixes —
now closed: region-less RVP allocation fails closed; weekly_service +
fund_requests/services fail-open staff_ids guards now unconditional.

DONE: export gate (require_export_permission on 14 org-dataset views; own-data
exports exempt by design); champion slots complete on ia_confirm incl.
assessment slot a1 linkage; leadership review() scoped to
_may_see_people_insight for staff_hr.

REMAINING for READY: final full suite green; weakest-intervention
consolidation (18 sites → recommendation_engine); HR empty registers
build-or-descope decision; reconciliation at seeded volume; mobile walkthrough;
backup-restore drill; budget_ceiling_ugx enforcement (or accept advisory —
product call, documented).

## CONTINUATION POINT (post export-gate narrowing)
Gate narrowed: school_directory_view + special_projects_my_plan_view ungated
(scoped own-data); regression now targets /partners?export=csv (ALL_ROLES page,
org register). Final suite bxfp51ekj running on the exact tree.
NEXT, in order: (1) commit on green; (2) weakest consolidation — swap the 11
school-level inline min()/sort sites onto ssa.recommendation_engine
.prioritized_interventions / school_recommendation, convergence test across
surfaces; (3) HR empty registers: DESCOPE recommendation — hide sidebar
entries for compliance/succession/compensation/payroll until writers exist
(honest absence beats empty page), or build minimal writers if user prefers;
(4) volume reconciliation: seed a month of activity via seed_demo, run money
chain, assert UGX 0; (5) mobile walkthrough of My Plan/evidence/leave/PD/
approvals at 390px via Client + template checks; (6) backup-restore drill
(pg_dump/restore + verify_chain).

## FINAL PASS (2026-07-22)
- Consolidation: 3 planning surfaces → full engine; setup list → bulk_weakest
  (canonical bulk form, honest contract); plan_builder/projects/pl_analytics/
  ssa_performance → canonical tie-break. 18 undocumented definitions → 2
  documented ones.
- HR: six writer-less registers descoped from navigation (direct URLs keep
  honest empty states).
- Volume reconciliation: 300 activities through the canonical funnel,
  planned == requested, UGX 0 difference — pinned as a permanent test.
- Backup-restore drill: pg_dump 2.6M → restore → 702 schools / 481 activities
  / 4628 audit rows intact.
- Audit chain: drill EXPOSED a real break (seq 3386, 4 duplicate seq values —
  concurrency race during parallel verification walks). Root cause: seq had
  no unique constraint. Fixed: unique constraint (migration audit.0003) +
  rebuild_audit_chain command; verify_chain now {'ok': True}.
- Mobile: five field workflows scanned — one unguarded table (leave PTO)
  fixed; design linter clean.

## PERFORMANCE FORM MANDATE — delta plan (2026-07-22)
BUILT+TESTED (commits 7a19e711 + uncommitted window layer, suite bq0bkbpm2):
live_progress (verified-only, derived on read); builder with real denominators;
partner weight; PD auto-merge + manual items; amendments (manual, no self-
approve); HR-only windows (priority_setting/q1/MID_YEAR=Q2/q3/YEAR_END=Q4);
immutable snapshots frozen at activation (proven: live moves, snapshot never);
3 distinct rating columns w/ scoped writers; readiness job (7-day HR notify,
registered, run twice, deduped).
REMAINING DELTA, in order:
1. Exact taxonomy: DEFAULT_TEMPLATES → categories Program Growth / Program
   Quality (School Visits, Training, SSA, Capital-mixed) / PD / Spiritual
   Formation / Edify Values. Capital = mixed (manual milestones + manager
   assessment), metric_key None.
2. ValueCommitment.kind field ("value"|"spiritual"); seed the SIX named
   values on agreement build: Christ like Service; Devoted to Prayer;
   Transformation through Relationships; All things done with excellence &
   high Integrity; Applaud entrepreneurial spirit; Best Idea Wins.
   ("Be joyful..." = versioned template decision, ask user, don't drop.)
3. PerformanceReview.functional_manager FK (configured) +
   save_functional_manager_input (third rating column writer).
4. Performance Support routing: flag → informal RecoveryPlan (exists, Phase
   9) recommendation service; NEVER auto-PIP (guard test).
5. Targets sync: on agreement approval write StaffTargetProfile rows from
   metric targets (check apps/targets StaffTargetProfile field names first).
6. Docgen: snapshot → printable HTML (role-scoped, audited download); DOCX
   only if python-docx already in requirements — check, do NOT add deps.
7. HR return/reopen with reason + audit (states beyond open/close).

## UI NORMALIZATION MANDATE (2026-07-22, mid-turn)
Gold standard = My Plan filter experience. Plan:
1. INSPECT My Plan filter implementation (templates/pages/my_plan/ + partials)
   → extract canonical components: FilterToolbar/FilterSelect/FilterDrawer/
   ActiveFilterChip/ClearFilters as shared template partials
   (templates/components/filters/*) with data-component attributes.
2. AUDIT (agents): every filter/dropdown/search per page — overlaps (negative
   margin/absolute over cards), arrow spacing (need pr-10 + right-3 arrow),
   duplicate search bars, native-vs-custom select mix.
3. APPLY: migrate pages to shared components; filters in document flow
   (Header → KPI → FilterToolbar → Content); max 3 inline + drawer.
4. SEARCH: one persistent top-bar search, contextual per module
   (?search= in URL, backend-scoped); remove page-level persistent search;
   keep only in-drawer selector search (documented exceptions).
5. TOPBAR: Messages icon beside bell (Search·Messages·Notifications·Help·
   Profile), unread badge = messages page count, SSE update, centered
   blurred panel desktop / full-screen mobile.
6. SAFEGUARDS: template lint tests (one persistent search per page, no
   absolute/negative-margin filter containers, select pr reserve, no dup ids)
   + responsive checks at 8 widths.

## URGENT-ATTENTION CARD MANDATE (2026-07-22)
SSA-first precedence: No SSA (critical, suppress ALL intervention labels) →
No Visit or Training → No Training → No Visit → canonical SSA recommendation.
Month-scoped (planned activities in selected month only), deduped per school,
role-scoped, scheduled-state as secondary text, 5-7 rows max. ONE backend
resolver (resolve_urgent_issue) reusing: latest confirmed-FY SSA, entitlement
gap (client 1+1, core slots), IA_VERIFIED completion, recommendation_engine.
Tests per §14. No logic in templates/JS/exports.

## TOPBAR SEARCH REWIRE PATTERN (locked from school_views.py:444)
context["topbar_search"] = {placeholder, input_id: "topbar-search-input",
value: q, hx_get: <page url>, hx_target: <results container>,
hx_trigger: "keyup delay:300ms, search", hx_include: "#<filter form id>"}.
Then DELETE the body search input (keep name="q"/"search" param handling in
the view). 21 pages listed in the inventory (messages, trainings, visits,
debriefs, projects×3, ia queue, planning, accounts, partners, hr pd,
notifications, leave approvals, evidence, disbursements, fund_requests,
clusters, fund_allocation, fund_approvals, country_budget). Drawer/modal
selector searches stay (documented exceptions). After rewires: template-lint
test — at most one persistent search input per rendered page, and it is the
topbar one.

## 12/10 READINESS MANDATE — master sequence (2026-07-22)
Order: (A) finish UI normalization [allowlist 9 → 0: accounts dashboard,
hr pd dashboard, evidence workspace, 6 finance partials; then mobile filter
drawer + clear-filters on gold standard; select-dialect convergence];
(B) performance-form delta [targets sync on approval, snapshot→printable
docgen (no new deps), HR return/reopen states]; (C) THE AUDIT:
1. Fresh baseline: check/migrations/ruff/format/test + collectstatic +
   tailwind build + system health run. Record all counts honestly.
2. Platform map + dependency graph (agents, compact outputs) → dead
   models/routes/jobs inventory.
3. Role Verification Matrix ×10 (walk nav/API/export/direct-URL per role).
4. DB integrity: constraints for §11 invariants (unique SF ID, unique
   partner payment [exists], unique target credit per source, unique core
   slot, etc.) + orphan/duplicate sweeps + idempotent repairs.
5. Concurrency pack §12 (threaded double-submit tests on the 8 money/credit
   mutations not yet covered).
6. §52 scenarios A-I as integration tests with real role accounts.
7. Security pack §48 (suspended/offboarded/replayed-invite/direct-URL/
   cross-country probes as tests).
8. Performance §47: seed 15k schools on staging DB, query budgets, p95s.
9. Failure injection §49 + backup/restore (done once — redo post-changes)
   + rollback rehearsal + 8h soak (start early, runs while auditing).
10. System Health: add missing §50 detectors.
11. Scorecard: 120-pt honest scoring, hard gates first. NO bonus while any
    core category incomplete. Everything fixed, not listed.

## SEARCH CONSOLIDATION — COMPLETE (2026-07-22)
Allowlist 21 → 0. Every page-level persistent search removed and bound to
the top bar (attach_to mode for GET filter forms, hx_* mode for HTMX pages).
IA queue's two inputs reclassified as filters (honest placeholders, kept).
Documented §17 exceptions: drawer/modal/compose pickers, pages/search,
pages/help, pages/messages/new (context-record picker).
TRAP FOUND TWICE: forms with hx-trigger "...changed from:input[name='q']"
match the TOPBAR input globally once the body input is gone → double-fire.
Detached on planning, clusters, fund_requests. CHECK THIS on any future
top-bar binding.
Guard: apps/frontend/test_search_consolidation.py (two-way — no new body
search may appear; allowlist may only shrink).
REMAINING UI WORK: mobile filter drawer + clear-filters on the My Plan gold
standard; select-dialect convergence (boxed vs pill wrappers).

## AUDIT BASELINE — TOOLING REALITY (2026-07-22, honest)
CONFIGURED AND RUNNABLE: manage.py check; makemigrations --check;
migrate --plan; ruff check; ruff format --check; manage.py test (1918);
scripts/normalize_legacy_primary_utilities.py --check (design linter);
node v24.14.0 + npm build (tailwind); collectstatic; system_health checks.
NOT INSTALLED IN THIS ENV (cannot be run; do NOT claim results):
pytest, coverage, mypy, bandit, playwright, axe/accessibility runner,
visual-regression runner, dependency CVE scanner.
→ Report these as NOT RUN with the reason, never as passed. Where a gate
depends on them (§4 coverage/mypy/bandit, §46 automated a11y), substitute
what CAN be proven: Django test suite, template/structural guards, manual
ORM probes, and say so explicitly in the scorecard.

## PROD BUILD CHAIN — VERIFIED (2026-07-22)
npm run build: OK. collectstatic under config.settings.prod: OK
(32 copied / 167 unmodified / 506 post-processed).
Boot guards fail CLOSED and were each proven by refusal:
  AUTHZ_MODE must be "enforce"; ENABLE_DEV_SEED must be false;
  FIELD_ENCRYPTION_KEY required AND must be 32 bytes (64 hex).
REQUIRED PROD ENV (deployment doc): SECRET_KEY, JWT_SECRET(>=16),
SUPER_ADMIN_PASSWORD, DATABASE_URL, ALLOWED_HOSTS, AUTHZ_MODE=enforce,
ENABLE_DEV_SEED=false, FIELD_ENCRYPTION_KEY=<64 hex>, plus
ENABLE_BACKGROUND_JOBS=true on the worker service only.
