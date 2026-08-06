# Workflow-Engine Conformance Report

**Date:** 2026-07-08
**Against:** the product operating model — *"the platform should not manually move schools between pages; it should create workflow records. Cluster creates Planning Work Items. Partner assignment creates Partner Assignment records. Scheduling creates Activities. Activities create Budgets. Activities appear in My Plan. Every page is a role-scoped view of the same workflow engine."*

**Method:** three independent read-only code traces (scheduling/budget core; planning + partner + project record flows; My Plan cards + system-health checks), each with file:line evidence.

---

## Headline verdict

**The workflow engine largely exists.** Every scheduling path already funnels through one service that blocks scheduling when catalogue rates are missing, snapshots cost lines (catalogue id + version, unit cost, quantity, currency, period), auto-creates advance requests, and generates the Weekly Fund Request from those lines. Rollups (weekly → monthly → quarterly → country) are computed live from the cost lines — budget is never entered by hand. Role scoping (CCEO own portfolio / PL supervised) conforms.

What breaks the spec is not missing architecture — it is **(a) a handful of wiring bugs inside the conforming flow, (b) an incoherent status vocabulary written four different ways, and (c) UI that computes the right things and then never renders them.**

### Do we need a `PlanningWorkItem` table? — Recommendation: **No.**

The spec's PlanningWorkItem statuses map 1:1 onto records that already exist:

| Spec status | Existing home |
|---|---|
| UNASSIGNED / CLUSTER_READY / READY_FOR_BASELINE_SSA / READY_FOR_SUPPORT / SCHEDULED / IN_MY_PLAN | `School.planning_readiness` — the enum (`apps/core/enums.py:62-78`) already contains almost all these values; the bug is that `recompute_quality_and_readiness` only ever writes three of them |
| PARTNER_ASSIGNED / PARTNER_PENDING_SCHEDULE | `PartnerAssignment.status` |
| PROJECT_COORDINATOR_QUEUE | `ProjectSchoolAssignment` + one new readiness value |
| CANCELLED | `Activity` / `PartnerAssignment` status |

A new table would duplicate four existing records and add a sync obligation to 10+ write sites — in a codebase that currently fails to keep even one status string coherent (PartnerAssignment status is written as `"assigned"`, `"pending_scheduling"`, `"partner_pending_schedule"`, and queried as a **never-written** fourth spelling). The enterprise fix is *persisting the existing statuses coherently*, not adding a fifth record type. A real table earns its keep only if per-item history or multiple concurrent work items per school become requirements.

---

## Defects found inside the conforming flow

### Fixed in this PR (no schema changes)

1. **Weekly Fund Request silently never generated for real staff** — cost lines are stamped with `User.id` but the auto-generator was called with `Activity.responsible_staff_id` (a StaffProfile id when one exists), so its line filter matched nothing. The single most damaging finance bug found: "scheduling creates the budget" worked, "budget rolls into the weekly request" didn't. *(apps/fund_requests/weekly_service.py, apps/activities/services.py)*
2. **100× budget understatement in My Plan** — `est_cost_cents / 100`, but the field stores whole UGX. Also replaced My Plan's invented cluster rates (participants × 15 000 + 50 000 + 100 000…) with the real scheduled budget from cost lines. *(apps/my_plan/services.py)*
3. **Catalogue pinning was cosmetic** — lines were stamped with a catalogue version, but pricing read *all* `CostSetting` rows regardless of catalogue. Pricing now filters to the resolved catalogue (unattached legacy rows fill gaps only). *(apps/budget/costing_service.py)*
4. **Two phantom statuses** — `returned_for_correction` was read by the My Plan "Returned" classification, the status pill, next-action logic and the returned-activities view but written by no code path (writers set `returned` / `returned_by_pl`); `"started"` was queried by five dashboards but never written (writers set `in_progress`). All read sites now use the written vocabulary. This is why the Returned/Needs-Correction workflow appeared permanently empty. *(apps/my_plan/services.py, apps/frontend/views/my_plan_views.py, staff_views.py, dashboard_views.py, apps/command_center/dashboard_service.py)*
5. **Inverted NetSuite rule** — an accounted advance **without** a NetSuite reference showed "Closed" and **with** one showed "Cleared". Missing ID is now the blocking `NetSuite ID Required` state per the finance model. *(apps/activities/models.py finance_status)*
6. **Partner-assigned schools didn't reliably leave Staff Planning** — the planning exclusion queried a status spelling nothing writes. All read sites now cover every written spelling, so "Assign to Partner" actually removes the school from the actionable staff queue and the "Partner Pending Schedule" readiness branch can fire. *(apps/planning/planning_service.py, apps/activities/services.py)*
7. **System Health lied** — the page read un-nested keys, so all ten workflow rows rendered "Clean" forever. Fixed, and the check suite extended (below).
8. **My Plan computed 7 of the spec's 8 card sections and rendered none of them** — Partner Planned (read-only monitoring), Returned/Needs Correction, Waiting on Approval, plus a new Finance/Accountability Pending list are now rendered as cards; staff mutating actions are hidden on partner-owned rows **and** rejected server-side (previously staff could Start / upload evidence / enter SF ID / submit on a partner activity — only Complete was incidentally blocked).
9. **Remaining fabricated money purged** — cost-preview fallback price list, command-center accountant KPIs, and the 450 000-UGX literals on ready-for-advance / cleared / completed-detail / monthly-request / partner-payments now bind real values or show "—".
10. **12 of the spec's 15 System Health workflow checks implemented** (clustered-school-not-in-planning, partner-assigned-still-in-staff-queue, partner work invisible to its partner, unowned scheduled activities, cluster activity without a cluster, project schools with no project activity, budget line without catalogue version, active plan without a date, terminal activities still in the feed, …). The remaining 3 need persisted planning state (Phase 2) and currently run as proxies.

### Requires schema / status migrations — proposed phases (not in this PR)

**Phase 2 — status coherence (small migrations, 1–2 days):**
- `PartnerAssignmentStatus` TextChoices (`assigned`, `pending_schedule`, `partner_scheduled`, `cancelled`, `returned`, …) + data migration collapsing the four spellings; update all writers/queriers.
- Make `School.recompute_quality_and_readiness` write the **full** readiness enum (partner-assigned → `ready_for_partner_assignment`, scheduled → `scheduled`/`in_my_plan`, project → new `project_coordinator_queue` value) and call it from every mutation, so Planning reads persisted state instead of re-deriving. This *is* the spec's PlanningWorkItem, persisted on the records that already exist.
- `Activity.source` (planning / project / partner), write `Activity.week` (computed but never stored), preserve original scheduling timestamp on cost lines across re-prices, convert `ActivityScheduleCostLine.catalogue_id` to a FK.
- Scope the partner-pending KPIs (currently a nationwide count for every user).

**Phase 3 — partner loop completion (2–3 days):**
- Stop creating a placeholder Activity at assign-to-partner (assignment ≠ scheduling); the drawer path currently creates one and the schedule-drawer-with-partner path even prices it — both violate "no budget until the partner schedules".
- Surface pending `PartnerAssignment` rows in the partner portal with a **Schedule** action wired to the existing `partner_schedule` service (it already does the right thing: atomic Activity + cost snapshot + assignment flip — there is simply no UI calling it).
- Fix ownership on partner-scheduled activities: `monitored_by_staff_id = assigning staff` (so it lands on the assigner's monitoring card), stop setting the partner user as `responsible_staff_id`, record `assigned_by`.
- Fix the four partner pages that filter on the wrong field (`responsible_staff_id` instead of `assigned_partner_id`) and are effectively empty today.
- Atomic add-to-cluster (`transaction.atomic` around assignment + school update + audit; the API path also lacks an audit log).

**Phase 4 — project coordinator surface (2–3 days):**
- A "Projects" tab in Planning fed by `ProjectSchoolAssignment` (the PC queue), PC scheduling passing `projectId` (the service already accepts it; no UI sends it), a Project Activities card in My Plan, `Activity.project_id` → FK.
- Message-Partner / Escalate actions on the monitoring card (the messaging backend already supports contextual threads; no UI exists).

**Phase 5 — presentation-layer status naming:** map internal states to the spec's labels (e.g. `awaiting_ia_verification` → "IA Pending") in one place; add the missing transient states (`ACTIVITY_SF_ID_ENTERED`) only if the lifecycle needs to pause there.

---

## Spec-section scorecard

| Spec section | Verdict | Notes |
|---|---|---|
| §2 Add to Cluster (10 atomic steps) | PARTIAL | 6 of 10 (assignment, status, audit, implicit surfacing, on-read recalcs); not atomic; no persisted work item |
| §3 Staff Planning scoped + actionable-only | CONFORMS | scoping + scheduled-work exclusion verified; partner exclusion bug fixed in this PR |
| §3 SSA-first recommendation | CONFORMS (wording differs) | "Schedule SSA Visit" + reason text; scheduling still allowed |
| §4 Staff schedules → Activity + budget + My Plan | CONFORMS | + weekly-request identity bug fixed in this PR |
| §9 Budget at scheduling + snapshot | CONFORMS | snapshot fields all exist; catalogue pinning made real in this PR; original-timestamp preservation → Phase 2 |
| §5 Assign to partner ≠ scheduling | PARTIAL | leaves queue (fixed) but still creates a placeholder Activity → Phase 3 |
| §6 Partner planning + partner schedules | PARTIAL | service conforms; no UI; partner pages filter wrong field → Phase 3 |
| §7 Partner activity dual visibility + read-only staff | PARTIAL → mostly fixed | monitoring card + UI/backend enforcement added in this PR; ownership fields → Phase 3 |
| §8 Cluster activity costing from catalogue | CONFORMS | engine correct; invented display rates removed in this PR |
| §10 Encumbrance vs disbursement language | CONFORMS | no template mislabels encumbered as disbursed; fabricated figures removed |
| §11 Special projects | MISSING (surface) | records exist; no PC queue/card → Phase 4 |
| §12 Ownership fields | PARTIAL | delivery_type/partner exist; assigned_by + source → Phase 2/3 |
| §13 My Plan card structure | PARTIAL → mostly fixed | 4 missing cards rendered in this PR; Core/Project split → Phase 4 |
| §14 Status taxonomies | PARTIAL | every concept exists; vocabulary scattered; phantom values fixed; canonical enums → Phase 2/5 |
| §15 Services | CONFORMS (names differ) | costing_service, weekly_service, planning_service, my_plan.services, partner_schedule cover the critical five |
| §16 System-health workflow checks | 12 of 15 in this PR | remaining 3 need Phase 2 persisted state |
