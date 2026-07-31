# Non-School Programme Activities, Work Plan and Central Calendar

**2026-07-30 · implementation report (§39)**

Governing rule implemented: *every amount in an operational budget originates
from a dated plan.* School, cluster, Core and Special Project work keep their
existing Planning workflows. Programme work that cannot originate from a school
or cluster plan — camps, conferences, retreats — is now planned as a dated
**Non-School Activity** through the same canonical Activity spine.

---

## 1. Existing services reused (no parallel systems)

Everything routes through the canonical funnel. Nothing here re-implements
scheduling, costing, funding, evidence or approval.

| Concern | Canonical service reused |
|---|---|
| Activity creation & state | `apps.activities.services.create` (the same 21-state lifecycle) |
| Costing | `apps.budget.costing.cost_for_activity` + `costing_service.apply_to_activity` |
| Cost catalogue | `apps.activity_catalogue` — the governed source catalogue |
| Weekly funding | `apps.fund_requests` weekly/advance services and their approval chains |
| Monthly / quarter / FY | `apps.monthly_work_plan.recompute_program_total` |
| My Plan | `apps.my_plan.services` (derived view — no second record) |
| Calendar | `extended_views.calendar_view` projection over the Activity queryset |
| Reschedule / cancel | `activities.services.reschedule` / `.cancel` |
| Evidence, Salesforce, IA, accountability, audit | unchanged canonical paths |

The only new service is a thin authorization wrapper,
`apps.planning.services.schedule_programme_activity`, which checks the
permission and delegates to `activities.services.create`.

## 2. Models extended (minimally)

`Activity` gained: `end_date`, `planning_source`, `activity_context_type`,
`support_rationale`, `venue`, `event_district`.
`ActivityCatalogueItem` gained: `non_school_allowed`, `multi_day_allowed`,
`requires_participant_counts`, `salesforce_id_required`,
`ia_verification_required`, `programme_category`.

Migrations: `activities.0031` (fields), `activities.0032` (backfills
`planning_source` for historical rows from their relations),
`activity_catalogue.0004` (capability flags).

## 3. Activity types — the governed catalogue is the authority

**Correction made during this build.** An earlier pass invented twelve generic
programme items (CONFERENCE, STUDENT_CAMP, …). That was a parallel catalogue and
has been removed. The real non-school programme activities are the source
catalogue's own **Group-delivered** items, now flagged `non_school_allowed`:

- Student Training — Youth camps
- Student Leadership Training — Students Camps
- Student Conference/Camps — Student camps
- Teacher Leadership Conference/Camp/Retreat

They remain fully school-schedulable as before; the flag only *adds* the option
to plan one centrally. New types need no template change — the drawer renders
whatever the catalogue marks `non_school_allowed`, grouped by
`programme_category`.

## 4. Non-school work is identified by PLANNING SOURCE

`planning_source == "manual_work_plan"` is the discriminator everywhere (§1/§2)
— not a single activity type. This matters because the governed camps deliver
under workflow kind `training`; keying on a type would have missed them.

## 5. Costing (§7/§9)

Group items price through the canonical group-training recipe
(participant meals per head, facilitation, venue), now **day-aware**: a 3-day
camp is 3 days of each per-day component. Single-day work is unchanged
(`days == 1`).

Cross-period allocation splits per-day components across the months they are
actually delivered in, one dated line per month, keyed `…#mYYYYMM` so the
one-component-per-key database constraint still holds.

**The split is total-preserving by construction** (largest-remainder on the
line's own amount, with an assertion). An earlier version divided *quantity* by
day count — `1 // 3 == 0` silently deleted whole components and rounded meals
down, so an activity cost less merely for crossing a month boundary. A
regression test now pins that a crossing activity costs exactly what the same
activity costs inside one month.

## 6. Entry points, permissions, routes

One drawer, one service, two entry points (§5): the Work Plan page and the
Fund/Budget dashboard, both `hx-get="/work-plan/add"`.

New permission `planning.manualActivity.create`, granted to CCEO, Program Lead,
Project Coordinator, Country Director, Impact Assessment, HR and Admin.
Accountant and partner roles are excluded and receive 403.

Routes: `/work-plan/add` (drawer), `/work-plan/add/preview` (live catalogue cost
preview), `/work-plan/add/action` (create).

## 7. Work Plan, Calendar, sidebar

`/work-plan` groups by month / quarter / FY with the mandated columns (Activity
Date, Activity Name, Responsible Person, Status, Cost, Next Action), multi-day
range labels, group subtotals, KPI strip and role scoping (RVP sees summary
bands without operational rows; Accountant reads without planning authority).

`/calendar` remains a projection of the Activity queryset — no second store. A
multi-day activity renders on each of its days but counts once, and appears in
the continuation month. Leave and holidays stay separate overlays.

Sidebar (MY WORK): My Plan → **Work Plan** → **Calendar**, rendering for CCEO,
PL, IA, Project Coordinator, CD, RVP, Accountant, HR and Admin.

## 8. Bugs found and fixed by end-to-end verification

1. **My Plan 500** — every school/cluster attribute in the row builder assumed
   one of the two existed; `a.school.cluster_id` ran whenever there was no
   cluster, so the first programme activity assigned to anyone took their whole
   My Plan page down. Guarded, and the row now names the venue instead of
   "Unknown School".
2. **Programme work invisible in My Plan** — it matched none of the three
   category tables. Added a Programme Activities section fed by planning source.
3. **Money-losing cross-month split** — see §5 above.
4. **`validate_context` demanded a school** for centrally-planned Group items;
   it now understands the non-school context and still enforces
   `non_school_allowed`, delivery permissions and project requirements.

## 9. Health checks (§35)

New `apps.activities.work_plan_health`, surfaced as `workPlan` in System Health:
missing rationale, missing date, end-before-start, missing responsible person,
unstamped planning source, and cross-month cost not allocated.

## 10. Notifications (§33)

`activity_assigned` and `cost_setup_required` fire at creation (best-effort,
never rolling back the plan). New scheduled job `activity_reminders` (07:00
daily) sends one "starts tomorrow" per activity per person, deduplicated by a
deterministic `source_event_id`.

## 11. Verification

Full end-to-end synchronization proof (one activity, every surface), run against
the live database and cleaned up afterwards:

```
1. CREATED    training  2026-08-31→2026-09-02  source=manual_work_plan
              lines=6  line_total == est_cost  ✓
2. PERIODS    {2026-08: 730,000, 2026-09: 1,460,000}  sum == total  ✓
3. WORKPLAN   exactly 1 row · "31 August – 2 September 2026" · cost == lines  ✓
4. MY PLAN    200 · activity present  ✓
5. CALENDAR   renders across its days · appears in continuation month  ✓
6. WEEKLY     all lines in ONE channel · no line in two requests  ✓
7. MONTHLY    Aug 730,000 ✓   Sep 1,460,000 ✓  (both match their lines)
8. HEALTH     healthy=True, all six checks pass  ✓
9. CANCEL     advances withdrawn · weekly lines removed  ✓
```

Tests: `apps/activities/test_programme_activities.py` — 34 passing, covering
creation, validation, permissions, costing, cross-period allocation, funding
flow, reschedule, My Plan handoff, health, and a `TransactionTestCase`
double-click race proving one activity survives concurrent submission.

Financial regression suite (activities, budget, fund_requests,
monthly_work_plan, daily_visit_batches, planning, my_plan): 402 passing.

Full fresh-database suite: **3,430 passing / 2,419 subtests**.

Gate work done as part of this change:
- `test_role_gating` no longer pins Calendar as a removed link, and now
  positively asserts Calendar and Work Plan ARE in the sidebar (citing the
  supersession).
- The six Work Plan KPI tiles were converted from hand-built dicts to
  `apps.core.metrics.render_metric`, with six new registry specs — so each
  tile carries its own definition, unit, period, finance stage and drilldown.
- `test_cluster_setup` payload updated for the edit drawer's newly required
  fields.

## 12. Remaining issues

None in this feature. Seven suite failures remain, all outside it and all in
another developer's concurrently-edited work:

| Failure | Owner |
|---|---|
| 4 × design-system geometry / type / primary-utility gates | `templates/pages/admin/user_detail.html`, `templates/pages/documents/upload_center.html` |
| `test_gold_standard_lints_are_clean` | same two templates |
| `test_all_roles_pages_are_an_explicit_decision` | `uploads` page opened to all roles (Upload Center change) |
| `test_one_underlying_activity_creates_one_credit_per_rule` | Strategic Priorities milestone credit |

Neither template nor either feature is touched by this change.
