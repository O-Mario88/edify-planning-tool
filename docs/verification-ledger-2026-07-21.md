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
